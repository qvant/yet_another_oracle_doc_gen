create view v_current_state as 
select *
  from t_hist_table t
 where t.dt_start <= localtimestamp
   and t.dt_stop > localtimestamp
   and t.b_deleted = 0
