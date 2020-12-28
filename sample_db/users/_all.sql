-- Create the user 
create user &&UNAME
  default tablespace &&TBSP
  temporary tablespace &DEF_TBSP
  quota unlimited on &&TBSP;
alter user &&UNAME identified by &PWD;
-- Grant/Revoke object privileges 
grant execute on DBMS_LOCK to &&UNAME;
grant execute on DBMS_SQL to &&UNAME;
-- Grant/Revoke system privileges 
grant create job to TEST_USER;
grant create materialized view to &&UNAME;
grant create procedure to &&UNAME;
grant create session to &&UNAME;
grant create table to &&UNAME;
grant create view to &&UNAME;
grant create trigger to &&UNAME;
grant create type to &&UNAME;
grant select any dictionary to &&UNAME;

