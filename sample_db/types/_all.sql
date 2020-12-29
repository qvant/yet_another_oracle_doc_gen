create type string_list as table of varchar2(255)
/
create type number_list as table of number
/
create type integer_list as table of number(10)
/
create type simple_varray as varray(255) of number(10);
/
create type float_varray as varray(255) of number(5, 2);
/