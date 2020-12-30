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
    if table_name is not None and table_owner is not None:
        return table_owner + '.' + table_name
    else:
        return ""


def replace_views(sql, available_views):
    for i in available_views.keys():
        sql = sql.replace(i, available_views[i])
    return sql


def gather_tables(connect, user, available_views):
    cursor = connect.cursor()
    sql_tables = """select t.table_name, c.comments, t.owner, t.temporary, t.iot_type, t.partitioned, t.nested
                      from all_tables t
                      left join all_tab_comments c
                        on t.owner = c.owner
                       and t.table_name = c.table_name
                    where t.owner = upper(:a)
                    and t.table_name not like 'BIN$%'
                    order by t.table_name"""
    sql_tables = replace_views(sql_tables, available_views)
    cursor.execute(sql_tables, {'a': user})

    tables = {}

    for table_name, table_comment, table_owner, temporary, iot_type, partitioned, nested in cursor:
        table_id = get_table_id(table_owner, table_name)
        table_type = M_TABLE_TYPE_HEAP
        if iot_type is not None:
            table_type = M_TABLE_TYPE_IOT
        elif temporary == 'Y':
            table_type = M_TABLE_TYPE_TEMP
        tables[table_id] = {"name": table_name, "comment": table_comment, "columns": {}, "type": TYPE_TABLE,
                            "unique_indexes": [], "table_type": table_type, "partitioned": partitioned == 'Y',
                            "triggers": [], "indexes": [], "nested": nested == 'YES'}

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
                            "unique_indexes": [], "triggers": [], "indexes": [], "nested": False}

    return tables


def gather_attrs(connect, user, tables, available_views):
    cursor = connect.cursor()
    sql_attrs = """
                    select t.owner, t.table_name, t.column_name, c.comments, t.owner, t.data_type, 
                        t.data_length, t.data_precision, t.data_scale, t.data_default, t.nullable, 
                        t.char_length, t.char_used, dt.owner as dt_owner, dt.type_name
                      from all_tab_columns t
                      left join all_col_comments c
                        on t.owner = c.owner
                       and t.table_name = c.table_name
                       and t.column_name = c.column_name
                      left join all_types dt
                        on dt.owner = t.data_type_owner
                       and t.data_type = dt.type_name
                     where t.owner = upper(:a)
                     order by t.table_name, t.column_name
                    """
    sql_attrs = replace_views(sql_attrs, available_views)
    cursor.execute(sql_attrs, {'a': user})

    prev_table_id = None
    attrs = {}
    for owner, table_name, column_name, comments, owner, data_type, data_length, data_precision, data_scale, \
            data_default, nullable, char_length, char_used, dt_owner, type_name in cursor:
        table_id = get_table_id(owner, table_name)
        if prev_table_id is None:
            prev_table_id = table_id
        if prev_table_id != table_id:
            tables[prev_table_id]["columns"].update(attrs)
            prev_table_id = table_id
            attrs = {}
        length_semantics = ''
        if char_used is not None:
            data_length = char_length
            if char_used == 'C':
                length_semantics = 'CHAR'
            else:
                length_semantics = 'BYTE'
        # remove quotas in defaults for string fields
        if data_default is not None:
            if data_default[0] == "'":
                data_default = data_default[1:-1]
        attrs[column_name] = {"name": column_name, "type": data_type, "length": data_length,
                              "precision": data_precision, "scale": data_scale, "default": data_default,
                              "comment": comments, "primary_key": False, "nullable": nullable == 'Y',
                              "length_semantics": length_semantics, "type_id": get_table_id(dt_owner, type_name)}
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
                    and c.constraint_name not like 'BIN$%'
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
                   from all_cons_columns cc where cc.owner = upper(:a) and cc.constraint_name not like 'BIN$%'
                   order by owner, table_name, constraint_name, position
                   """
    sql_constraint_columns = replace_views(sql_constraint_columns, available_views)

    cursor.execute(sql_constraint_columns, {'a': user})
    for constraint_name, column_name in cursor:
        constraints[constraint_name]["columns"].append(column_name)

    return constraints


def gather_indexes(connect, user, available_views):
    indexes = {}
    cursor = connect.cursor()
    sql_indexes = """
                    select i.table_owner, i.table_name, i.index_type, i.index_name, i.owner as index_owner
                      from all_indexes i
                     where i.table_owner = upper(:a)
                       and i.table_name not like 'BIN$%'
                     order by i.table_owner, i.table_name, i.index_name
                    """
    sql_indexes = replace_views(sql_indexes, available_views)
    cursor.execute(sql_indexes, {'a': user})
    for table_owner, table_name, index_type, index_name, index_owner in cursor:
        indexes[index_name] = {"table": get_table_id(table_owner, table_name), "type": index_type,
                               "columns": [], "columns_order": [], " owner": index_owner, "name": index_name}

    sql_index_columns = """
                        select i.table_owner, i.table_name, i.index_name, i.owner as index_owner, 
                               c.column_name, c.descend, t.data_default
                          from all_indexes i
                          join all_ind_columns c
                            on i.owner = c.index_owner
                           and i.index_name = c.index_name
                          left join all_tab_cols t
                            on t.owner = i.table_owner
                           and t.table_name = i.table_name
                           and t.column_name = c.column_name
                           and t.virtual_column = 'YES'
                         where i.table_owner = upper(:a)
                           and i.table_name not like 'BIN$%'
                         order by i.table_owner, i.table_name, i.index_name, c.column_position
                        """
    sql_index_columns = replace_views(sql_index_columns, available_views)
    cursor.execute(sql_index_columns, {'a': user})
    for table_owner, table_name, index_name, index_owner, column_name, descend, data_default in cursor:
        # get formula for functional indexes
        if data_default is not None:
            column_name = data_default
        indexes[index_name]["columns"].append(column_name)
        indexes[index_name]["columns_order"].append(descend)
    return indexes


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


def gather_types(connect, user, available_views):

    cursor = connect.cursor()
    sql_types = """
                select t.owner, t.type_name, t.typecode
                  from all_types t
                  where t.owner = upper(:a)
                 order by t.owner, t.type_name
                """
    sql_types = replace_views(sql_types, available_views)

    cursor.execute(sql_types, {'a': user})
    types = {}
    for owner, type_name, type_code in cursor:
        types[get_table_id(owner, type_name)] = {"name": type_name, "code": type_code,
                                                 "type_id": get_table_id(owner, type_name),
                                                 "is_array": False, "is_object": False, "attrs": [], "methods": []}

    sql_types = """
                    select t.owner, t.type_name, t.coll_type, t.upper_bound, t.elem_type_name, t.length, t.precision,
                        t.scale
                      from all_coll_types t
                      where t.owner = upper(:a)
                     order by t.owner, t.type_name
                    """
    sql_types = replace_views(sql_types, available_views)

    cursor.execute(sql_types, {'a': user})
    for owner, type_name, coll_type, upper_bound, elem_type_name, length, precision, scale in cursor:
        types[get_table_id(owner, type_name)]["is_array"] = True
        types[get_table_id(owner, type_name)]["array_type"] = coll_type
        types[get_table_id(owner, type_name)]["array_size"] = upper_bound
        types[get_table_id(owner, type_name)]["array_elem_type"] = elem_type_name
        types[get_table_id(owner, type_name)]["array_elem_len"] = length
        types[get_table_id(owner, type_name)]["array_elem_precision"] = precision
        types[get_table_id(owner, type_name)]["array_elem_scale"] = scale

    sql_types = """
                        select t.owner, t.type_name, t.attr_name, t.attr_type_owner, t.attr_type_mod, t.attr_type_name, 
                            t.precision, t.scale, t.attr_no, t.length
                          from all_type_attrs t
                          where t.owner = upper(:a)
                         order by t.owner, t.type_name, attr_no
                        """
    sql_types = replace_views(sql_types, available_views)

    cursor.execute(sql_types, {'a': user})
    for owner, type_name, attr_name, attr_type_owner, attr_type_mod, attr_type_name, precision, scale, \
        attr_no, length in cursor:
        types[get_table_id(owner, type_name)]["is_object"] = True
        attr = {"precision": precision, "scale": scale, "attr_no": attr_no, "name": attr_name,
                "type": attr_type_name, "type_id": get_table_id(attr_type_owner, attr_type_name), "length": length}
        types[get_table_id(owner, type_name)]["attrs"].append(attr)

    sql_types = """
                        select t.owner, t.type_name, t.method_name, t.method_no
                          from all_type_methods t
                          where t.owner = upper(:a)
                         order by t.owner, t.type_name, method_no
                        """
    sql_types = replace_views(sql_types, available_views)

    cursor.execute(sql_types, {'a': user})

    for owner, type_name, method_name, method_no in cursor:
        types[get_table_id(owner, type_name)]["is_object"] = True
        method = {"name": method_name, "scale": scale, "method_no": method_no}
        types[get_table_id(owner, type_name)]["methods"].append(method)

    return types


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


def process_indexes(tables, indexes):
    for i in indexes:
        table_id = indexes[i]["table"]
        tables[table_id]["indexes"].append(indexes[i])
    return tables


def make_report_header(file, tables, types, schema, trans, gen_user):
    file.init()
    file.add_header("{}: {}".format(trans.get_message(M_SCHEMA), schema))
    file.add_header("{}: {}".format(trans.get_message(M_GENERATED_AS), gen_user))
    if len(tables) > 0:
        file.add_header("{}".format(trans.get_message(M_TABLES)))
        for i in tables:
            if tables[i]["nested"]:
                continue
            file.add_link(i, tables[i]["name"])
            file.new_line()
    if len(types) > 0:
        file.add_header("{}".format(trans.get_message(M_TYPES)))
        for i in types:
            file.add_link(i, types[i]["name"])
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
    if len(attr["type_id"]) > 0:
        file.open_table_cell()
        file.add_link(attr["type_id"], attr["type"])
        file.close_table_cell()
    else:
        file.add_table_cell(attr["type"])
    file.add_table_cell(str(attr["length"]))
    file.add_table_cell(str(attr["length_semantics"]))
    if attr["precision"] is not None:
        file.add_table_cell(str(attr["precision"]))
    else:
        file.add_table_cell('')
    if attr["scale"] is not None:
        file.add_table_cell(str(attr["scale"]))
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
        file.add_table_cell(trans.translate_bool(True))
    else:
        file.add_table_cell('')
    if attr["comment"] is not None:
        file.add_table_cell(str(attr["comment"]))
    else:
        file.add_table_cell('')
    file.close_table_row()


def make_report_unique_index(file, index):
    file.write(index["name"])
    file.new_line()
    file.add_list(index["columns"])


def make_report_index(file, index):
    arr_len = len(index["columns"])
    if arr_len > 0:
        file.write(index["name"])
        file.new_line()
        file.open_list()
        for i in range(len(index["columns"])):
            file.add_list_element("{0} {1}".format(index["columns"][i], index["columns_order"][i]))
        file.close_list()


def make_report_tables(file, tables, trans):
    for i in tables:
        # don't need nested tables storage in report
        if tables[i]["nested"]:
            continue
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
        file.add_table_cell(trans.get_message(M_COLUMN_LENGTH_SEMANTICS))
        file.add_table_cell(trans.get_message(M_COLUMN_PRECISION))
        file.add_table_cell(trans.get_message(M_COLUMN_SCALE))
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
                make_report_unique_index(file, j)
        if len(tables[i]["indexes"]) > 0:
            file.new_line()
            file.write("{}:".format(trans.get_message(M_INDEXES)))
            file.new_line()
            file.new_line()
            for j in tables[i]["indexes"]:
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


def make_report_types(file, types, trans):
    if len(types) == 0:
        return
    file.add_header(trans.get_message(M_TYPES))

    for i in types:
        file.add_link_anchor(types[i]["type_id"])
        file.add_header(types[i]["name"], 2)
        file.write("{0}: {1}".format(trans.get_message(M_TYPE), types[i]["code"]))
        file.new_line()
        if types[i]["is_array"]:
            file.write("{0}: {1}".format(trans.get_message(M_ARRAY_TYPE), types[i]["array_type"]))
            file.new_line()
            if types[i]["array_size"] is not None:
                file.write("{0}: {1}".format(trans.get_message(M_ARRAY_SIZE), types[i]["array_size"]))
            else:
                file.write("{0}: {1}".format(trans.get_message(M_ARRAY_SIZE), trans.get_message(M_UNBOUNDED)))
            file.new_line()
            file.write("{0}: {1}".format(trans.get_message(M_COLUMN_TYPE), types[i]["array_elem_type"]))
            file.new_line()
            if types[i]["array_elem_len"] is not None:
                file.write("{0}: {1}".format(trans.get_message(M_COLUMN_LENGTH), types[i]["array_elem_len"]))
                file.new_line()
            if types[i]["array_elem_precision"] is not None:
                file.write("{0}: {1}".format(trans.get_message(M_COLUMN_PRECISION), types[i]["array_elem_precision"]))
                file.new_line()
            if types[i]["array_elem_scale"] is not None:
                file.write("{0}: {1}".format(trans.get_message(M_COLUMN_SCALE), types[i]["array_elem_scale"]))
                file.new_line()
        elif types[i]["is_object"]:
            if len(types[i]["methods"]) > 0:
                file.write(trans.get_message(M_METHODS))
                file.open_list()
                for m in types[i]["methods"]:
                    file.add_list_element(m["name"])
                file.close_list()
            file.new_line()
            file.add_table()
            file.open_table_row()
            file.add_table_cell(trans.get_message(M_ATTR_NAME))
            file.add_table_cell(trans.get_message(M_COLUMN_TYPE))
            file.add_table_cell(trans.get_message(M_COLUMN_LENGTH))
            file.add_table_cell(trans.get_message(M_COLUMN_PRECISION))
            file.add_table_cell(trans.get_message(M_COLUMN_SCALE))
            file.close_table_row()
            file.write(trans.get_message(M_ATTRS))
            for attr in types[i]["attrs"]:
                file.open_table_row()
                file.add_table_cell(attr["name"])
                if len(attr["type_id"]) > 0:
                    file.open_table_cell()
                    file.add_link(attr["type_id"], attr["type_id"])
                    file.close_table_cell()
                else:
                    file.add_table_cell(attr["type"])
                file.add_table_cell(attr["length"])
                file.add_table_cell(attr["precision"])
                file.add_table_cell(attr["scale"])
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


def make_report(tables, queues, types, run_stats, filename, schema, locale, gen_user, file_type):
    run_stats["start_report"] = datetime.datetime.now()
    translator = L18n()
    translator.set_locale(locale)
    report = Report(file_type)
    report.set_file(filename)
    make_report_header(report, tables, types, schema, translator, gen_user)
    make_report_tables(report, tables, translator)
    make_report_queues(report, queues, translator)
    make_report_types(report, types, translator)
    make_report_footer(report, run_stats, translator)
    report.close()


def get_system_views(connect, use_dba):
    views_temp = ["all_tables", "all_tab_comments", "all_views", "all_tab_columns", "all_col_comments",
                  "all_constraints", "all_cons_columns", "all_triggers", "all_queues", "all_indexes",
                  "all_ind_columns", "all_types", "all_coll_types", "all_type_attrs", "all_type_methods"]
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
        schema_indexes = gather_indexes(connect, target_user, db_views)
        triggers_constraints = gather_triggers(connect, target_user, db_views)
        queues = gather_queues(connect, target_user, db_views)
        types = gather_types(connect, target_user, db_views)
        run_stats["end_gather"] = datetime.datetime.now()
        run_stats["start_process"] = datetime.datetime.now()
        schema_info = process_constraints(schema_info, schema_constraints)
        schema_info = process_triggers(schema_info, triggers_constraints)
        schema_info = process_indexes(schema_info, schema_indexes)
    except cx_Oracle.DatabaseError as exc:
        error, = exc.args
        print("NLS_LANG: " + os.environ.get("NLS_LANG"))
        print("Database version : " + str(get_version(connect)))
        print(error.message)
        raise
    run_stats["end_process"] = datetime.datetime.now()
    make_report(schema_info, queues, types, run_stats, args.file, target_user, locale, args.user, file_type)
    if args.interactive:
        print('Job finished')


if __name__ == '__main__':
    main()
