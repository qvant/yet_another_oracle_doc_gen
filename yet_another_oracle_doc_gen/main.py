import cx_Oracle
import datetime
import argparse
import getpass
import os
from yet_another_oracle_doc_gen.l18n import L18n
from yet_another_oracle_doc_gen.messages import *
from yet_another_oracle_doc_gen.reports import Report

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


def make_report_header(file, tables, schema, trans, gen_user):
    file.init()
    file.add_header("{}: {}".format(trans.get_message(M_SCHEMA), schema))
    file.add_header("{}: {}".format(trans.get_message(M_GENERATED_AS), gen_user))
    file.add_header("{}".format(trans.get_message(M_TABLES)))
    for i in tables:
        file.add_link(i, tables[i]["name"])
        file.new_line()


def make_report_footer(file, run_stats, trans):
    file.add_header(trans.get_message(M_EXEC_TIME))
    file.add_table()
    file.add_table_row([trans.get_message(M_METADATA_GATHER_BEGIN), run_stats["start_gather"]])
    file.add_table_row([trans.get_message(M_METADATA_GATHER_END), run_stats["end_gather"]])
    file.add_table_row([trans.get_message(M_METADATA_PROCESS_BEGIN), run_stats["start_process"]])
    file.add_table_row([trans.get_message(M_METADATA_PROCESS_END), run_stats["end_process"]])
    file.add_table_row([trans.get_message(M_REPORT_PROCESS_BEGIN), run_stats["start_report"]])
    run_stats["end_report"] = datetime.datetime.now()
    file.add_table_row([trans.get_message(M_REPORT_PROCESS_END), run_stats["end_report"]])
    file.close_table()


def make_report_attr(file, attr, trans):
    file.open_table_row()
    file.add_table_cell(attr["name"])
    file.add_table_cell(attr["type"])
    file.add_table_cell(str(attr["length"]))
    if attr["precision"] is not None:
        file.add_table_cell(str(attr["precision"]))
    else:
        file.add_table_cell('')
    if attr["default"] is not None:
        file.add_table_cell(str(attr["default"]))
    else:
        file.add_table_cell('NULL')
    if attr["primary_key"]:
        file.add_table_cell(trans.translate_bool(True))
    else:
        file.add_table_cell('')
    if "ref_table" in attr.keys():
        file.open_table_cell()
        file.add_link(attr["ref_table"], attr["ref_table"])
        file.close_table_cell()
    else:
        file.add_table_cell('')
    if "check" in attr.keys():
        file.add_table_cell(attr["check"])
    else:
        file.add_table_cell('')
    if attr["nullable"]:
        file.add_table_cell('')
    else:
        file.add_table_cell(trans.translate_bool(True))
    if attr["comment"] is not None:
        file.add_table_cell(str(attr["comment"]))
    else:
        file.add_table_cell('')
    file.close_table_row()


def make_report_index(file, index):
    file.write(index["name"])
    file.new_line()
    file.add_list(index["columns"])


def make_report_tables(file, tables, trans):
    for i in tables:
        file.add_link_anchor(i)
        file.add_header(tables[i]["name"], 2)
        file.write("{}: {}".format(trans.get_message(M_TABLE), tables[i]["name"]))
        file.new_line()
        file.write("{}: {}".format(trans.get_message(M_TABLE_OR_VIEW), trans.get_message(tables[i]["type"])))
        file.new_line()
        if "table_type" in tables[i].keys():
            file.write("{}: {}".format(trans.get_message(M_TABLE_CATEGORY),
                                       trans.get_message(tables[i]["table_type"])))
            file.new_line()
        if "partitioned" in tables[i].keys():
            file.write("{}: {}".format(trans.get_message(M_IS_PARTITIONED),
                                       trans.translate_bool(tables[i]["partitioned"])))
            file.new_line()
        if tables[i]["comment"] is not None and len(tables[i]["comment"]) > 0:
            file.write("{}: {}".format(trans.get_message(M_COMMENT), tables[i]["comment"]))
            file.new_line()
        file.write("{}:".format(trans.get_message(M_COLUMNS)))
        file.new_line()
        file.add_table()
        file.open_table_row()
        file.add_table_cell(trans.get_message(M_COLUMN_NAME))
        file.add_table_cell(trans.get_message(M_COLUMN_TYPE))
        file.add_table_cell(trans.get_message(M_COLUMN_LENGTH))
        file.add_table_cell(trans.get_message(M_COLUMN_PRECISION))
        file.add_table_cell(trans.get_message(M_COLUMN_DEFAULT))
        file.add_table_cell(trans.get_message(M_COLUMN_PK))
        file.add_table_cell(trans.get_message(M_COLUMN_FK))
        file.add_table_cell(trans.get_message(M_COLUMN_CHECK))
        file.add_table_cell(trans.get_message(M_COLUMN_NULLABLE))
        file.add_table_cell(trans.get_message(M_COMMENT))
        file.close_table_row()
        for j in tables[i]["columns"]:
            make_report_attr(file, tables[i]["columns"][j], trans)
        file.close_table()
        if len(tables[i]["unique_indexes"]) > 0:
            file.new_line()
            file.write("{}:".format(trans.get_message(M_UNIQUE_CONSTRAINTS)))
            file.new_line()
            file.new_line()
            for j in tables[i]["unique_indexes"]:
                make_report_index(file, j)
        make_report_triggers(file, tables[i]["triggers"], trans)


def make_report_queues(file, queues, trans):
    if len(queues) == 0:
        return
    file.add_header(trans.get_message(M_QUEUES))
    file.open_table()
    file.open_table_row()
    file.add_table_cell(trans.get_message(M_QUEUE))
    file.add_table_cell(trans.get_message(M_TABLE))
    file.add_table_cell(trans.get_message(M_QUEUE_TYPE))
    file.add_table_cell(trans.get_message(M_COMMENT))
    file.close_table_row()
    for i in queues:
        file.open_table_row()
        file.add_table_cell(queues[i]["name"])
        file.open_table_cell()
        file.add_link(queues[i]["table"], queues[i]["table"])
        file.close_table_cell()
        file.add_table_cell(queues[i]["type"])
        file.add_table_cell(queues[i]["comment"])
        file.close_table_row()

    file.close_table()


def make_report_triggers(file, triggers, trans):
    if len(triggers) > 0:
        file.new_line()
        file.write("{}:".format(trans.get_message(M_TRIGGERS)))
        file.new_line()
        file.add_table()
        file.open_table_row()
        file.add_table_cell(trans.get_message(M_TRIGGER_NAME))
        file.add_table_cell(trans.get_message(M_TRIGGER_EVENT))
        file.add_table_cell(trans.get_message(M_TRIGGER_ACTION))
        file.close_table_row()
        for i in triggers:
            file.open_table_row()
            file.add_table_cell(i["owner"] + "." + i["name"])
            file.add_table_cell(i["type"])
            file.add_table_cell(i["event"])
            file.close_table_row()
        file.close_table()


def make_report(tables, queues, run_stats, filename, schema, locale, gen_user, file_type):
    run_stats["start_report"] = datetime.datetime.now()
    translator = L18n()
    translator.set_locale(locale)
    report = Report(file_type)
    report.set_file(filename)
    make_report_header(report, tables, schema, translator, gen_user)
    make_report_tables(report, tables, translator)
    make_report_queues(report, queues, translator)
    make_report_footer(report, run_stats, translator)
    report.close()


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
    parser.add_argument("--file_type", "-ft", help="File type, html or docx", action="store", default='html')
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
    file_type = args.file_type.upper()
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
    make_report(schema_info, queues, run_stats, args.file, target_user, locale, args.user, file_type)
    if args.interactive:
        print('Job finished')


if __name__ == '__main__':
    main()
