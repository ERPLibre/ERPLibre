-- © 2021-2026 TechnoLibre (http://www.technolibre.ca)
-- License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
--
-- Odoo 13.0 -> 14.0 : hand the « group_fiscal_year » security group over to
-- the module that owns it in 14.0.
--
-- In 13.0 the group « Allow to define fiscal years of more or less than a
-- year » is declared by the core « account » module, so the database holds it
-- as account.group_fiscal_year. In 14.0 core account no longer declares it and
-- om_account_accountant (odoomates) does. During the upgrade that module finds
-- no XML id of its own, tries to CREATE the group, and hits:
--
--   duplicate key value violates unique constraint "res_groups_name_uniq"
--   Key (category_id, name)=(9, Allow to define fiscal years ...) already exists
--
-- Renaming the XML id makes Odoo UPDATE the existing row instead of creating a
-- duplicate. The record id is untouched, so any user assignment, access right
-- or record rule pointing at the group survives.
--
-- Runs through psql, not the Odoo shell: at this point the database is still
-- 13.0 and loading it with the 14.0 registry is exactly what fails.

UPDATE ir_model_data
   SET module = 'om_account_accountant'
 WHERE model = 'res.groups'
   AND module = 'account'
   AND name = 'group_fiscal_year'
   -- Only when that module is actually part of this database.
   AND EXISTS (
        SELECT 1 FROM ir_module_module
         WHERE name = 'om_account_accountant'
           AND state IN ('installed', 'to upgrade', 'to install')
   )
   -- Idempotent: do nothing if the target XML id already exists.
   AND NOT EXISTS (
        SELECT 1 FROM ir_model_data
         WHERE module = 'om_account_accountant'
           AND name = 'group_fiscal_year'
   );
