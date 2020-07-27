import cx_Oracle
import datetime
import argparse
import codecs
import getpass
import os
from l18n import L18n
from messages import *

TYPE_TABLE = M_TABLE_TYPE_T
TYPE_VIEW = M_TABLE_TYPE_W


def get_connect(args):
    credentials = {"user": args.user, "password": args.password, "tns": args.tns}
    if args.sysdba:
        mode = cx_Oracle.SYSDBA
    else:
        mode = cx_Oracle.DEFAULT_AUTH

    connect = cx_Oracle.connect(credentials["user"], credentials["password"], credentials["tns"], mode=mode)
    return connect


def get_version(connect):
    cursor = connect.cursor()
    cursor.execute("""select version from product_component_version""")
    db_ver, = cursor.fetchone()
    db_ver = db_ver.split('.')[0]
    return int(db_ver)


def get_table_id(table_owner, table_name):
    return table_owner + '.' + table_name


def replace_views(sql, available_views):
    for i in available_views.keys():
        sql = sql.replace(i, available_views[i])
    return sql


def gather_tables(connect, user, available_views):
    cursor = connect.cursor()
    sql_tables = """select t.table_name, c.comments, t.owner, t.temporary, t.iot_type, t.partitioned
                      from all_tables t
                      left join all_tab_comments c
                        on t.owner = c.owner
                       and t.table_name = c.table_name
                    where t.owner = upper(:a)
                    order by t.table_name"""
    sql_tables = replace_views(sql_tables, available_views)
    cursor.execute(sql_tables, {'a': user})

    tables = {}

    for table_name, table_comment, table_owner, temporary, iot_type, partitioned in cursor:
        table_id = get_table_id(table_owner, table_name)
        table_type = M_TABLE_TYPE_HEAP
        if iot_type is not None:
            table_type = M_TABLE_TYPE_IOT
        elif temporary == 'Y':
            table_type = M_TABLE_TYPE_TEMP
        tables[table_id] = {"name": table_name, "comment": table_comment, "columns": {}, "type": TYPE_TABLE,
                            "unique_indexes": [], "table_type": table_type, "partitioned": partitioned == 'Y',
                            "triggers": []}

    sql_views = """select t.view_name, c.comments, t.owner
                      from all_views t
                      left join all_tab_comments c
                        on t.owner = c.owner
                       and t.view_name = c.table_name
                     where t.owner = upper(:a)
                     order by t.view_name
                    """
    sql_views = replace_views(sql_views, available_views)
    cursor.execute(sql_views, {'a': user})

    for table_name, table_comment, table_owner in cursor:
        table_id = get_table_id(table_owner, table_name)
        tables[table_id] = {"name": table_name, "comment": table_comment, "columns": {}, "type": TYPE_VIEW,
                            "unique_indexes": [], "triggers": []}

    return tables


def gather_attrs(connect, user, tables, available_views):
    cursor = connect.cursor()
    sql_attrs = """
                    select t.owner, t.table_name, t.column_name, c.comments, t.owner, t.data_type, 
                        t.data_length, t.data_precision, t.data_scale, t.data_default, t.nullable
                      from all_tab_columns t
                      left join all_col_comments c
                        on t.owner = c.owner
                       and t.table_name = c.table_name
                       and t.column_name = c.column_name
                     where t.owner = upper(:a)
                     order by t.table_name, t.column_name
                    """
    sql_attrs = replace_views(sql_attrs, available_views)
    cursor.execute(sql_attrs, {'a': user})

    prev_table_id = None
    attrs = {}
    for owner, table_name, column_name, comments, owner, data_type, data_length, data_precision, data_scale, \
            data_default, nullable in cursor:
        table_id = get_table_id(owner, table_name)
        if prev_table_id is None:
            prev_table_id = table_id
        if prev_table_id != table_id:
            tables[prev_table_id]["columns"].update(attrs)
            prev_table_id = table_id
            attrs = {}
        attrs[column_name] = {"name": column_name, "type": data_type, "length": data_length,
                              "precision": data_precision, "scale": data_scale, "default": data_default,
                              "comment": comments, "primary_key": False, "nullable": nullable == 'Y'}
    if prev_table_id is not None:
        tables[prev_table_id]["columns"].update(attrs)
    return tables


def gather_constraints(connect, user, available_views):

    cursor = connect.cursor()
    sql_constraints = """
                select c.table_name, c.constraint_type, c.constraint_name, c.owner, search_condition, 
                    r_constraint_name, index_owner, index_name
                  from all_constraints c
                  where c.owner = upper(:a)
                 order by c.owner, c.table_name, c.constraint_name
                """
    sql_constraints = replace_views(sql_constraints, available_views)

    cursor.execute(sql_constraints, {'a': user})
    constraints = {}
    for table_name, constraint_type, constraint_name, owner, search_condition, ref_constr, index_owner, index_name \
            in cursor:
        constraints[constraint_name] = {"table": get_table_id(owner, table_name), "type": constraint_type,
                                        "columns": [], 'check': search_condition, 'index_owner': index_owner,
                                        'index_name': index_name, "ref_constr": ref_constr}
    sql_constraint_columns = """
                   select 
                     cc.constraint_name,
                     cc.column_name 
                   from all_cons_columns cc where cc.owner = upper(:a)
                   order by owner, table_name, constraint_name, position
                   """
    sql_constraint_columns = replace_views(sql_constraint_columns, available_views)

    cursor.execute(sql_constraint_columns, {'a': user})
    for constraint_name, column_name in cursor:
        constraints[constraint_name]["columns"].append(column_name)

    return constraints


def gather_triggers(connect, user, available_views):

    cursor = connect.cursor()
    sql_triggers = """
                select t.table_owner, t.trigger_name, t.trigger_type, t.triggering_event, t.table_name, t.owner
                  from all_triggers t
                  where t.table_owner = upper(:a)
                 order by t.owner, t.table_name, t.trigger_name
                """
    sql_triggers = replace_views(sql_triggers, available_views)

    cursor.execute(sql_triggers, {'a': user})
    triggers = {}
    for owner, trigger_name, trigger_type, triggering_event, table_name, trigger_owner in cursor:
        if table_name is None:
            continue
        triggers[get_table_id(trigger_owner, trigger_name)] = {"table": get_table_id(owner, table_name),
                                                               "type": trigger_type, "event": triggering_event,
                                                               "name": trigger_name, "owner": trigger_owner}

    return triggers


def gather_queues(connect, user, available_views):

    cursor = connect.cursor()
    sql_triggers = """
                select t.owner, t.name, t.queue_table, t.user_comment, t.queue_type
                  from all_queues t
                  where t.owner = upper(:a)
                 order by t.owner, t.name, t.queue_table
                """
    sql_triggers = replace_views(sql_triggers, available_views)

    cursor.execute(sql_triggers, {'a': user})
    queues = {}
    for owner, q_name, q_table, q_comment, q_type in cursor:
        queues[get_table_id(owner, q_name)] = {"name": q_name, "table": get_table_id(owner, q_table), "comment": q_comment,
                                               "type": q_type}

    return queues


def process_constraints(tables, constraints):
    for i in constraints:
        table_id = constraints[i]["table"]
        if constraints[i]["type"] == 'P':
            for j in (constraints[i]["columns"]):
                tables[table_id]["columns"][j]["primary_key"] = True
            tables[table_id]["unique_indexes"].append({"name": i, "columns": constraints[i]["columns"]})
        elif constraints[i]["type"] == 'R':
            ref_table = constraints[constraints[i]["ref_constr"]]["table"]
            for j in (constraints[i]["columns"]):
                tables[table_id]["columns"][j]["ref_table"] = ref_table
        elif constraints[i]["type"] == 'C':
            if constraints[i]["check"] == '''"''' + constraints[i]["columns"][0] + '''" IS NOT NULL''':
                continue
            for j in (constraints[i]["columns"]):
                tables[table_id]["columns"][j]["check"] = constraints[i]["check"]
        elif constraints[i]["type"] == 'U':
            tables[table_id]["unique_indexes"].append({"name": i, "columns": constraints[i]["columns"]})
    return tables


def process_triggers(tables, triggers):
    for i in triggers:
        table_id = triggers[i]["table"]
        tables[table_id]["triggers"].append(triggers[i])
    return tables


def make_report_header(file, tables, schema, trans):
    file.write("<html>")
    file.write("<body>")
    file.write("<h1> {}: {}</h1>".format(trans.get_message(M_SCHEMA), schema))
    file.write("<h1>{}</h1>".format(trans.get_message(M_TABLES)))
    for i in tables:
        file.write('''<a href="#''' + i + '''">''')
        file.write(tables[i]["name"] + '''</a><br>''')


def make_report_footer(file, run_stats, trans):
    file.write("<h1>{}:</h1>".format(trans.get_message(M_EXEC_TIME)))
    file.write("<table border = 1>")
    file.write("<tr><td>")
    file.write("{} </td><td>{}".format(trans.get_message(M_METADATA_GATHER_BEGIN), run_stats["start_gather"]))
    file.write("</td></tr><tr><td>")
    file.write("{} </td><td>{}".format(trans.get_message(M_METADATA_GATHER_END), run_stats["end_gather"]))
    file.write("</td></tr><tr><td>")
    file.write("{} </td><td>{}".format(trans.get_message(M_METADATA_PROCESS_BEGIN), run_stats["start_process"]))
    file.write("</td></tr><tr><td>")
    file.write("{} </td><td>{}".format(trans.get_message(M_METADATA_PROCESS_END), run_stats["end_process"]))
    file.write("</td></tr><tr><td>")
    file.write("{} </td><td>{}".format(trans.get_message(M_REPORT_PROCESS_BEGIN), run_stats["start_report"]))
    file.write("</td></tr><tr><td>")
    run_stats["end_report"] = datetime.datetime.now()
    file.write("{}: </td><td>{}".format(trans.get_message(M_REPORT_PROCESS_END), run_stats["end_report"]))
    file.write("</td></tr>")
    file.write("</table>")
    file.write("</body>")
    file.write("</html>")


def make_report_attr(file, attr, trans):
    file.write("<tr>")
    file.write("<td>" + attr["name"] + "</td>")
    file.write("<td>" + attr["type"] + "</td>")
    file.write("<td>" + str(attr["length"]) + "</td>")
    if attr["precision"] is not None:
        file.write("<td>" + str(attr["precision"]) + "</td>")
    else:
        file.write("<td></td>")
    if attr["default"] is not None:
        file.write("<td>" + str(attr["default"]) + "</td>")
    else:
        file.write("<td>NULL</td>")
    if attr["primary_key"]:
        file.write("<td>{}</td>".format(trans.translate_bool(True)))
    else:
        file.write("<td></td>")
    if "ref_table" in attr.keys():
        file.write('''<td><a href="#''' + attr["ref_table"] + '''">''' + attr["ref_table"] + '''</td>''')
    else:
        file.write("<td></td>")
    if "check" in attr.keys():
        file.write("<td>" + attr["check"] + "</td>")
    else:
        file.write("<td></td>")
    if attr["nullable"]:
        file.write("<td></td>")
    else:
        file.write("<td>{}</td>".format(trans.translate_bool(True)))
    if attr["comment"] is not None:
        file.write("<td>" + str(attr["comment"]) + "</td>")
    else:
        file.write("<td></td>")
    file.write("</tr>")


def make_report_index(file, index):
    file.write(index["name"])
    file.write("<br><ul>")
    for i in index["columns"]:
        file.write("<li>")
        file.write(i)
        file.write("</li>")
    file.write("</ul>")


def make_report_tables(file, tables, trans):
    for i in tables:
        file.write('''<a id="''' + i + '''"</a>''')
        file.write("<h2>" + tables[i]["name"] + "</h2>")
        file.write("{}: {}<br>".format(trans.get_message(M_TABLE), tables[i]["name"]))
        file.write("{}: {}<br>".format(trans.get_message(M_TABLE_OR_VIEW), trans.get_message(tables[i]["type"])))
        if "table_type" in tables[i].keys():
            file.write("{}: {}<br>".format(trans.get_message(M_TABLE_CATEGORY),
                                           trans.get_message(tables[i]["table_type"])))
        if "partitioned" in tables[i].keys():
            file.write("{}: {}<br>".format(trans.get_message(M_IS_PARTITIONED),
                                           trans.translate_bool(tables[i]["partitioned"])))
        if tables[i]["comment"] is not None and len(tables[i]["comment"]) > 0:
            file.write("{}: {}<br>".format(trans.get_message(M_COMMENT), tables[i]["comment"]))
        file.write("{}:<br>".format(trans.get_message(M_COLUMNS)))
        file.write("<table border = 1>")
        file.write("<tr>")
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_NAME)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_TYPE)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_LENGTH)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_PRECISION)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_DEFAULT)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_PK)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_FK)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_CHECK)))
        file.write("<td>{}</td>".format(trans.get_message(M_COLUMN_NULLABLE)))
        file.write("<td>{}</td>".format(trans.get_message(M_COMMENT)))
        file.write("</tr>")
        for j in tables[i]["columns"]:
            make_report_attr(file, tables[i]["columns"][j], trans)
        file.write("</table>")
        if len(tables[i]["unique_indexes"]) > 0:
            file.write('''<br>''')
            file.write("{}: <br><br>".format(trans.get_message(M_UNIQUE_CONSTRAINTS)))
            for j in tables[i]["unique_indexes"]:
                make_report_index(file, j)
        make_report_triggers(file, tables[i]["triggers"], trans)


def make_report_queues(file, queues, trans):
    if len(queues) == 0:
        return
    file.write("<h1>" + trans.get_message(M_QUEUES) + "</h1>")
    file.write("<table border = 1>")
    file.write("<tr>")
    file.write("<td>{}</td>".format(trans.get_message(M_QUEUE)))
    file.write("<td>{}</td>".format(trans.get_message(M_TABLE)))
    file.write("<td>{}</td>".format(trans.get_message(M_QUEUE_TYPE)))
    file.write("<td>{}</td>".format(trans.get_message(M_COMMENT)))
    file.write("</tr>")
    for i in queues:
        file.write("<tr>")
        file.write("<td>{}</td>".format(queues[i]["name"]))
        file.write("<td><a href=\"#{}\">{}</a></td>".format(queues[i]["table"], queues[i]["table"]))
        file.write("<td>{}</td>".format(queues[i]["type"]))
        file.write("<td>{}</td>".format(queues[i]["comment"]))
        file.write("</tr>")

    file.write("</table>")


def make_report_triggers(file, triggers, trans):
    if len(triggers) > 0:
        file.write('''<br>''')
        file.write("{}:<br>".format(trans.get_message(M_TRIGGERS)))
        file.write("<table border = 1>")
        file.write("<tr>")
        file.write("<td>{}</td>".format(trans.get_message(M_TRIGGER_NAME)))
        file.write("<td>{}</td>".format(trans.get_message(M_TRIGGER_EVENT)))
        file.write("<td>{}</td>".format(trans.get_message(M_TRIGGER_ACTION)))
        file.write("</tr>")
        for i in triggers:
            file.write("<tr>")
            file.write("<td>{}</td>".format(i["owner"] + "." + i["name"]))
            file.write("<td>{}</td>".format(i["type"]))
            file.write("<td>{}</td>".format(i["event"]))
            file.write("</tr>")
        file.write("</table>")


def make_report(tables, queues, run_stats, filename, schema, locale):
    run_stats["start_report"] = datetime.datetime.now()
    f = codecs.open(filename, 'w', "utf-8")
    translator = L18n()
    translator.set_locale(locale)
    make_report_header(f, tables, schema, translator)
    make_report_tables(f, tables, translator)
    make_report_queues(f, queues, translator)
    make_report_footer(f, run_stats, translator)
    f.close()


def get_system_views(connect, use_dba):
    views_temp = ["all_tables", "all_tab_comments", "all_views", "all_tab_columns", "all_col_comments",
                  "all_constraints", "all_cons_columns", "all_triggers", "all_queues"]
    views = {}
    dba_views = []
    for i in views_temp:
        views[i] = i
        dba_views.append("dba" + i[3:])
    if use_dba:
        sql = '''select lower(view_name) from all_views where view_name in ('{}')'''.\
            format("','".join(dba_views).upper())
        cursor = connect.cursor()
        cursor.execute(sql)
        for view_name, in cursor:
            views["all" + view_name[3:]] = view_name
    return views


def get_settings():
    parser = argparse.ArgumentParser(description='Generate Oracle RDBMS schema description.')
    parser.add_argument("--interactive", '-i', help="Interactive workmode", action="store_true", default=False)
    parser.add_argument("--dba", '-d', help="Use dba views if possible. If not, all_* would be used.",
                        action="store_true", default=False)
    parser.add_argument("--sysdba", '-s', help="Connect as sysdba", action="store_true", default=False)
    parser.add_argument("--locale", "-l", help="Localization file name, should be in l18n folder", action="store",
                        default="english")
    parser.add_argument("--file", "-f", help="Report file", action="store")
    parser.add_argument("--user", "-u", help="User for gathering metadata", action="store")
    parser.add_argument("--password", "-p", help="Password", action="store")
    parser.add_argument("--tns", "-t", help="TNS for gathering metadata", action="store")
    parser.add_argument("--target_user", "-r",
                        help="Target schema for documentation. If not specified, connect schema used", action="store")
    args = parser.parse_args()
    if args.interactive:
        if args.user is None:
            args.user = input('Username: ')
        if args.password is None:
            args.password = getpass.getpass()
        if args.tns is None:
            args.tns = input('TNS: ')
        if args.target_user is None:
            args.target_user = input('Target schema(empty for connect schema: ')
        if args.file is None:
            args.file = input('Report filename: ')
    if args.target_user is None:
        args.target_user = args.user
    return args


def main():
    args = get_settings()
    connect = get_connect(args)
    target_user = args.target_user
    locale = args.locale
    use_dba = args.dba
    run_stats = {"start_gather": datetime.datetime.now()}
    try:
        db_views = get_system_views(connect, use_dba)
        schema_info = gather_tables(connect, target_user, db_views)
        schema_info = gather_attrs(connect, target_user, schema_info, db_views)
        schema_constraints = gather_constraints(connect, target_user, db_views)
        triggers_constraints = gather_triggers(connect, target_user, db_views)
        queues = gather_queues(connect, target_user, db_views)
        run_stats["end_gather"] = datetime.datetime.now()
        run_stats["start_process"] = datetime.datetime.now()
        schema_info = process_constraints(schema_info, schema_constraints)
        schema_info = process_triggers(schema_info, triggers_constraints)
    except cx_Oracle.DatabaseError as exc:
        error, = exc.args
        print("NLS_LANG: " + os.environ.get("NLS_LANG"))
        print("Database version : " + str(get_version(connect)))
        print(error.message)
        raise
    run_stats["end_process"] = datetime.datetime.now()
    make_report(schema_info, queues, run_stats, args.file, target_user, locale)
    if args.interactive:
        print('Job finished')


if __name__ == '__main__':
    main()
