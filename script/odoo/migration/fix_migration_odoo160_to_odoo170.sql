-- © 2021-2026 TechnoLibre (http://www.technolibre.ca)
-- License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
--
-- Correctifs à appliquer AVANT qu'OpenUpgrade ne migre vers Odoo 17.
--
-- En SQL et non en Python : ce fichier tourne sur une base encore en
-- 16, que le code de la 17 ne saurait pas charger.

-- Règles « Refresh … » laissées par muk_web_client_refresh.
--
-- Ce module d'Odoo 12 ajoute l'état `refresh` aux actions serveur et crée,
-- à son installation, une règle d'automatisation par modèle (« Refresh
-- Users on Update », …) sans identifiant XML. Il n'existe pas en 13 : son
-- uninstall_hook, qui retire ces règles, ne tourne donc jamais, et elles
-- traversent les versions avec un état que plus aucun code ne déclare.
--
-- Odoo 13 à 16 les ignorent. En 17, le script d'OpenUpgrade
-- `base_automation/17.0.1.0/end-migration.py` recalcule le nom de chaque
-- action serveur d'une règle, et `_compute_name` cherche l'état dans la
-- sélection du champ :
--   KeyError: 'refresh'
-- La migration s'arrête et la base reste à moitié migrée.
--
-- Sans le module, ces règles ne font rien : elles envoyaient un ordre de
-- rafraîchissement au client web du module. Elles partent avec leur action
-- serveur. base_automation et ir_cron refusent la suppression d'une action
-- qu'ils désignent (ON DELETE RESTRICT) : la règle part d'abord, et une
-- action qu'un cron désignerait reste. Rejouable : sans table ou sans
-- action `refresh`, rien ne change.
DO $$
DECLARE
    regles integer := 0;
    actions integer := 0;
BEGIN
    IF to_regclass('ir_act_server') IS NULL THEN
        RETURN;
    END IF;
    IF to_regclass('base_automation') IS NOT NULL THEN
        DELETE FROM base_automation
        WHERE action_server_id IN (
            SELECT id FROM ir_act_server WHERE state = 'refresh'
        );
        GET DIAGNOSTICS regles = ROW_COUNT;
    END IF;
    DELETE FROM ir_act_server a
    WHERE a.state = 'refresh'
      AND NOT EXISTS (
          SELECT 1 FROM ir_cron c WHERE c.ir_actions_server_id = a.id
      );
    GET DIAGNOSTICS actions = ROW_COUNT;
    IF regles + actions > 0 THEN
        RAISE NOTICE 'muk_web_client_refresh : % regle(s), % action(s) serveur retiree(s)',
            regles, actions;
    END IF;
END $$;
