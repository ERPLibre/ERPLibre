#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

# This script fix the module mail when migrating postgresql 17 to postgresql 18
print("Running a script in the Odoo shell!")

# This fix
# odoo.sql_db: bad query: b'ALTER TABLE "discuss_channel_member" ADD FOREIGN KEY ("channel_id") REFERENCES "discuss_channel"("id") ON DELETE cascade'
# ERROR: insert or update on table "discuss_channel_member" violates foreign key constraint "discuss_channel_member_channel_id_fkey"
# DÉTAIL : Key (channel_id)=(3) is not present in table "discuss_channel".

env.cr.execute("""
    ALTER TABLE discuss_channel
    DROP CONSTRAINT discuss_channel_channel_type_not_null;
""")
env.cr.commit()

#env.cr.execute("SELECT to_regclass('public.discuss_channel');")
#print("table:", env.cr.fetchone())

#print(
#    "model discuss.channel:",
#    env["ir.model"].search([("model", "=", "discuss.channel")]),
#)

print("End fix migration with update mail postgresql 17 to postgresql 18.")
