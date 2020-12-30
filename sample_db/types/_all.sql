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
create or replace type t_obj as object
(
  id   number,
  name varchar2(255),
  member function get_name return varchar2,
  constructor function t_obj(id number, name varchar2)
    return self as result
)
/
create or replace type body t_obj is
  constructor function t_obj(id number, name varchar2) return self as result is
  begin
    self.id   := id;
    self.name := name;
    return;
  end;

  member function get_name return varchar2
  is
  begin
    return self.name;
  end;
end;
/
create or replace type t_obj_complex as object
(
  id   number,
  name varchar2(255),
  complex_field t_obj
)
/