# ERPLibre

## Migration procedure production

TODO

## Migration procedure dev

Example : 

update module helpdesk_mgmt and helpdesk_join_team

update translation all

Remove helpdesk_res_partner_team

Delete module not found

smile_upgrade?

update html categorie_id

join_team == 6

servicecall == 1

--limit-time-real 99999 -c config.conf --stop-after-init -d santelibre -i helpdesk_mrp -i erplibre_base_enterprise_mrp,erplibre_base_hackaton,helpdesk_mgmt -u helpdesk_join_team

--limit-time-real 99999 -c config.conf --stop-after-init -d santelibre  -u helpdesk_join_team
