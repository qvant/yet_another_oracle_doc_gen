import cx_Oracle
import datetime
import argparse
import getpass
import os

TYPE_TABLE = 'Таблица'
TYPE_VIEW = 'Представление'


def get_connect(args):
    credentials = {"user": args.user, "password": args.password, "tns": args.tns}

    connect = cx_Oracle.connect(credentials["user"], credentials["password"], credentials["tns"])
    return connect


def get_version(connect):
    cursor = connect.cursor()
    cursor.execute("""select version from product_component_version""")
    db_ver, = cursor.fetchone()
    db_ver = db_ver.split('.')[0]
    return int(db_ver)


def get_table_id(table_owner, table_name):
    return table_owner + '.' + table_name


def gather_tables(connect, user):
    cursor = connect.cursor()

    cursor.execute("""
    select t.table_name, c.comments, t.owner, t.temporary, t.iot_type, t.partitioned
      from all_tables t
      left join all_tab_comments c
        on t.owner = c.owner
       and t.table_name = c.table_name
     where t.owner = upper(:a)
     order by t.table_name
    """, {'a': user})

    tables = {}

    for table_name, table_comment, table_owner, temporary, iot_type, partitioned in cursor:
        table_id = get_table_id(table_owner, table_name)
        table_type = "Heap"
        if iot_type is not None:
            table_type = "IOT"
        elif temporary == 'Y':
            table_type = 'Temp'
        tables[table_id] = {"name": table_name, "comment": table_comment, "columns": {}, "type": TYPE_TABLE,
                            "unique_indexes": [], "table_type": table_type, "partitioned": partitioned == 'Y'}

    cursor.execute("""
        select t.view_name, c.comments, t.owner
          from all_views t
          left join all_tab_comments c
            on t.owner = c.owner
           and t.view_name = c.table_name
         where t.owner = upper(:a)
         order by t.view_name
        """, {'a': user})

    for table_name, table_comment, table_owner in cursor:
        table_id = get_table_id(table_owner, table_name)
        tables[table_id] = {"name": table_name, "comment": table_comment, "columns": {}, "type": TYPE_VIEW,
                            "unique_indexes": []}

    return tables


def gather_attrs(connect, user, tables):
    cursor = connect.cursor()

    cursor.execute("""
    select t.owner, t.table_name, t.column_name, c.comments, t.owner, t.data_type, 
        t.data_length, t.data_precision, t.data_scale, t.data_default, t.nullable
      from all_tab_columns t
      left join all_col_comments c
        on t.owner = c.owner
       and t.table_name = c.table_name
       and t.column_name = c.column_name
     where t.owner = upper(:a)
     order by t.table_name, t.column_name
    """, {'a': user})

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


def gather_constraints(connect, user):

    cursor = connect.cursor()

    cursor.execute("""
        select c.table_name, c.constraint_type, c.constraint_name, c.owner, search_condition, 
            r_constraint_name, index_owner, index_name
          from all_constraints c
          where c.owner = upper(:a)
         order by c.owner, c.table_name, c.constraint_name
        """, {'a': user})
    constraints = {}
    for table_name, constraint_type, constraint_name, owner, search_condition, ref_constr, index_owner, index_name \
            in cursor:
        constraints[constraint_name] = {"table": get_table_id(owner, table_name), "type": constraint_type,
                                        "columns": [], 'check': search_condition, 'index_owner': index_owner,
                                        'index_name': index_name, "ref_constr": ref_constr}

    cursor.execute("""
            select 
              cc.constraint_name,
              cc.column_name 
            from all_cons_columns cc where cc.owner = upper(:a)
            order by owner, table_name, constraint_name, position
            """, {'a': user})
    for constraint_name, column_name in cursor:
        constraints[constraint_name]["columns"].append(column_name)

    return constraints


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


def make_report_header(file, tables, schema):
    file.write("<html>")
    file.write("<body>")
    file.write("<h1>Схема: " + schema + "</h1>")
    file.write("<h1>Таблицы</h1>")
    for i in tables:
        file.write('''<a href="#''' + i + '''">''')
        file.write(tables[i]["name"] + '''</a><br>''')


def make_report_footer(file, run_stats):
    file.write("<h1>Время выполнения:</h1>")
    file.write("<table border = 1>")
    file.write("<tr><td>")
    file.write("Начало получения метаданных: " + "</td><td>" + str(run_stats["start_gather"]))
    file.write("</td></tr><tr><td>")
    file.write("Окончание получения метаданных: " + "</td><td>" + str(run_stats["end_gather"]))
    file.write("</td></tr><tr><td>")
    file.write("Начало обработки метаданных: " + "</td><td>" + str(run_stats["start_process"]))
    file.write("</td></tr><tr><td>")
    file.write("Окончание обработки метаданных: " + "</td><td>" + str(run_stats["end_process"]))
    file.write("</td></tr><tr><td>")
    file.write("Начало формирования отчета: " + "</td><td>" + str(run_stats["start_report"]))
    file.write("</td></tr><tr><td>")
    run_stats["end_report"] = datetime.datetime.now()
    file.write("Окончание обработки отчета: " + "</td><td>" + str(run_stats["end_report"]))
    file.write("</td></tr>")
    file.write("</table>")
    file.write("</body>")
    file.write("</html>")


def make_report_attr(file, attr):
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
        file.write("<td>Да</td>")
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
        file.write("<td>Да</td>")
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


def make_report_tables(file, tables):
    for i in tables:
        file.write('''<a id="''' + i + '''"</a>''')
        file.write("<h2>" + tables[i]["name"] + "</h2>")
        file.write("Таблица: " + tables[i]["name"] + "<br>")
        file.write("Тип: " + tables[i]["type"] + "<br>")
        if "table_type" in tables[i].keys():
            file.write("Тип таблицы: " + str(tables[i]["table_type"]) + "<br>")
        if "partitioned" in tables[i].keys():
            file.write("Секционирована: " + str(tables[i]["partitioned"]) + "<br>")
        if tables[i]["comment"] is not None and len(tables[i]["comment"]) > 0:
            file.write("Описание: " + tables[i]["comment"] + "<br>")
        file.write("Столбцы:<br>")
        file.write("<table border = 1>")
        file.write("<tr>")
        file.write("<td>Название</td>")
        file.write("<td>Тип</td>")
        file.write("<td>Длина</td>")
        file.write("<td>Точность</td>")
        file.write("<td>Значение по умолчанию</td>")
        file.write("<td>PK</td>")
        file.write("<td>FK</td>")
        file.write("<td>Проверка</td>")
        file.write("<td>NOT NULL</td>")
        file.write("<td>Описание</td>")
        file.write("</tr>")
        for j in tables[i]["columns"]:
            make_report_attr(file, tables[i]["columns"][j])
        file.write("</table>")
        if len(tables[i]["unique_indexes"]) > 0:
            file.write('''<br>''')
            file.write("Ограничения уникальности: <br><br>")
            for j in tables[i]["unique_indexes"]:
                make_report_index(file, j)


def make_report(tables, run_stats, filename, schema):
    run_stats["start_report"] = datetime.datetime.now()
    f = open(filename, 'w')
    make_report_header(f, tables, schema)
    make_report_tables(f, tables)
    make_report_footer(f, run_stats)
    f.close()


def get_settings():
    parser = argparse.ArgumentParser(description='Generate Oracle RDBMS schema description.')
    parser.add_argument("--interactive", '-i', help="Interactive workmode", action="store_true", default=False)
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
    run_stats = {"start_gather": datetime.datetime.now()}
    try:
        schema_info = gather_tables(connect, target_user)
        schema_info = gather_attrs(connect, target_user, schema_info)
        schema_constraints = gather_constraints(connect, target_user)
        run_stats["end_gather"] = datetime.datetime.now()
        run_stats["start_process"] = datetime.datetime.now()
        schema_info = process_constraints(schema_info, schema_constraints)
    except cx_Oracle.DatabaseError as exc:
        error, = exc.args
        print("NLS_LANG: " + os.environ.get("NLS_LANG"))
        print("Database version : " + str(get_version(connect)))
        print(error.message)
        raise
    run_stats["end_process"] = datetime.datetime.now()
    make_report(schema_info, run_stats, args.file, target_user)
    if args.interactive:
        print('Job finished')


if __name__ == '__main__':
    main()
