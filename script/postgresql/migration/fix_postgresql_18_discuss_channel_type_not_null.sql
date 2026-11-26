-- © 2021-2026 TechnoLibre (http://www.technolibre.ca)
-- License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
--
-- Retire la contrainte NOT NULL nommée discuss_channel_channel_type_not_null
-- d'une base Odoo 17 ou plus passée de PostgreSQL 17 à 18.
--
-- PostgreSQL 18 enregistre chaque NOT NULL dans pg_constraint sous le nom
-- <table>_<colonne>_not_null. Sur une base qui la porte, la mise à jour du
-- module mail échoue à recréer la clé étrangère channel_id de
-- discuss_channel_member : « Key (channel_id)=(N) is not present in table
-- "discuss_channel" ». Sans la contrainte, la mise à jour passe, et Odoo
-- repose lui-même le NOT NULL du champ requis channel_type.
--
-- Idempotent : sans la table ou sans la contrainte, rien ne change. Lancé
-- par todo_upgrade.py quand la neutralisation échoue sur cette signature,
-- ou à la main :
--   psql -v ON_ERROR_STOP=1 -d <base> -f <ce fichier>

ALTER TABLE IF EXISTS discuss_channel
    DROP CONSTRAINT IF EXISTS discuss_channel_channel_type_not_null;
