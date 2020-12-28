create table t_dict
(
       id number,
       name varchar2(255) not null,
       description varchar2(255) default 'No description',
       constraint pk_t_dict primary key (id)
);
comment on table t_dict is 'Dictionary table';
comment on column t_dict.id is 'Unique id';
comment on column t_dict.name is 'Record name';
comment on column t_dict.description is 'Record description';

create table t_hist_table
(
       id number,
       dt_start timestamp with time zone not null,
       dt_stop timestamp with time zone not null,
       dict_id number not null,
       b_deleted number(1) default 0 not null,
       constraint pk_t_hist_table primary key (id),
       constraint fk_hist_dict foreign key(dict_id) references t_dict(id),
       constraint check_hist_del_flag check (b_deleted in (0, 1))
);
comment on table t_hist_table is 'Historical table';
comment on column t_hist_table.id is 'Unique id';
comment on column t_hist_table.dt_start is 'Timestamp of record start';
comment on column t_hist_table.dt_stop is 'Timestamp of record stop';
comment on column t_hist_table.dict_id is 'Reference to t_dict';
comment on column t_hist_table.b_deleted is 'Logical deletion flag';

create table t_types
(
       id number,
       n_integer number(10),
       char_string char(32),
       varchar_string varchar(32),
       varchar2_string varchar2(32),
       varchar2_byte_semantic varchar2(32 byte),
       varchar2_char_semantic varchar2(32 char),
       nchar_string nchar(255),
       nvarchar2_string nvarchar2(255),
       dt_date date,
       dt_lts0 timestamp(0) with local time zone,
       dt_ts   timestamp,
       dt_tstz timestamp with time zone,
       long_string clob,
       long_national_string nclob,
       long_binary blob,
       short_blob  long,
       file_pointer bfile,
       interval_ytm interval year to month,
       interval_dts interval day to second,
       constraint pk_t_types primary key (id)
);
comment on table t_types is 'Just set of columns with different types';
comment on column t_types.id is 'Unique id';
comment on column t_types.n_integer is 'Very long integer';
comment on column t_types.char_string is 'String of type CHAR';
comment on column t_types.varchar_string is 'String of type varchar';
comment on column t_types.varchar2_string is 'String of type varchar2';
comment on column t_types.varchar2_byte_semantic is 'String with length in bytes';
comment on column t_types.varchar2_char_semantic is 'String with length in symbols';
comment on column t_types.nchar_string is 'String of type nchar';
comment on column t_types.nvarchar2_string is 'String of type nvarchar2';
comment on column t_types.dt_date is 'Just date field';
comment on column t_types.dt_lts0 is 'Local timestamp, rounded to seconds';
comment on column t_types.dt_ts is 'Timestamp field';
comment on column t_types.dt_tstz is 'Timestamp with time zone field';
comment on column t_types.long_string is 'Very long string';
comment on column t_types.long_national_string is 'Very long national symbols string';
comment on column t_types.long_binary is 'Blob field';
comment on column t_types.short_blob is 'Short binary field';
comment on column t_types.file_pointer is 'File pointer';
comment on column t_types.interval_ytm is 'Interval year to month field';
comment on column t_types.interval_dts is 'Interval day to second field';

create table t_types_long
(
       id number,
       old_blob    long raw,
       constraint pk_t_types_long primary key (id),
       constraint fk_long_types foreign key(id) references t_types(id)
);
comment on table t_types_long is 'Just extension of t_types with long raw';
comment on column t_types_long.id is 'Unique id';
comment on column t_types_long.old_blob is 'Long raw field. Depricated type';

create table t_iot
(
       id number,
       v_name varchar2(128),
       constraint pk_t_iot primary key (id)
) organization index;

comment on table t_iot is 'Simple index organized table';
comment on column t_iot.id is 'Unique id';
comment on column t_iot.v_name is 'Record name';

create table t_indexed_table
(
       id number,
       dt_start timestamp with time zone not null,
       dt_stop timestamp with time zone not null,
       dict_id number not null,
       b_deleted number(1) default 0 not null,
       v_name varchar2(255),
       constraint pk_t_indexed_table primary key (id),
       constraint fk_ind_dict foreign key(dict_id) references t_dict(id),
       constraint check_ind_del_flag check (b_deleted in (0, 1))
);
create index idx_t_indexed_table_v_name on t_indexed_table(v_name);
comment on table t_indexed_table is 'Table with simple index';
comment on column t_indexed_table.id is 'Unique id';
comment on column t_indexed_table.dt_start is 'Timestamp of record start';
comment on column t_indexed_table.dt_stop is 'Timestamp of record stop';
comment on column t_indexed_table.dict_id is 'Reference to t_dict';
comment on column t_indexed_table.b_deleted is 'Logical deletion flag';
comment on column t_indexed_table.v_name is 'Indexed string field';

create table t_func_indexed_table
(
       id number,
       dt_start timestamp with time zone not null,
       dt_stop timestamp with time zone not null,
       dict_id number not null,
       b_deleted number(1) default 0 not null,
       v_name varchar2(255),
       constraint pk_t_func_indexed_table primary key (id),
       constraint fk_func_ind_dict foreign key(dict_id) references t_dict(id),
       constraint check_func_ind_del_flag check (b_deleted in (0, 1))
);
create index idx_t_func_indexed_table_v_name on t_func_indexed_table(upper(v_name));
comment on table t_func_indexed_table is 'Table with functional index';
comment on column t_func_indexed_table.id is 'Unique id';
comment on column t_func_indexed_table.dt_start is 'Timestamp of record start';
comment on column t_func_indexed_table.dt_stop is 'Timestamp of record stop';
comment on column t_func_indexed_table.dict_id is 'Reference to t_dict';
comment on column t_func_indexed_table.b_deleted is 'Logical deletion flag';
comment on column t_func_indexed_table.v_name is 'Indexed string field';
