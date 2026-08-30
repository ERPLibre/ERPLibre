-- © 2021-2026 TechnoLibre (http://www.technolibre.ca)
-- License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
--
-- Correctifs à appliquer AVANT qu'OpenUpgrade ne migre vers Odoo 18.
--
-- En SQL et non en Python : ce fichier tourne sur une base encore en
-- 17, que le code de la 18 ne saurait pas charger.

-- forum_tag_rel : la colonne qui pointe vers forum.post s'appelait
-- `forum_id` — un nom trompeur, elle ne désignait pas un forum. La 18 la
-- nomme `forum_post_id`.
--
-- OpenUpgrade le DÉCLARE dans son analyse :
--   website_forum / forum.post / tag_ids (many2many)
--     : column1 is now 'forum_post_id' ('forum_id') [forum_tag_rel]
-- mais `website_forum/18.0.1.2/` ne contient aucun script : rien ne
-- l'applique. Le chargement casse alors sur
--   column "forum_post_id" referenced in foreign key constraint does not exist
-- et la base reste à moitié migrée.
--
-- Les deux conditions rendent l'ordre rejouable : rien à faire si la
-- table n'existe pas (website_forum non installé) ni si le renommage a
-- déjà eu lieu.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forum_tag_rel' AND column_name = 'forum_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'forum_tag_rel' AND column_name = 'forum_post_id'
    ) THEN
        ALTER TABLE forum_tag_rel RENAME COLUMN forum_id TO forum_post_id;
        RAISE NOTICE 'forum_tag_rel.forum_id renommee en forum_post_id';
    END IF;
END $$;

-- account_root : une VUE SQL qu'Odoo 17 créait pour le modèle
-- `account.root` (son init() bâtissait la vue sur account_account.code),
-- et que la 18 a orphelinée sans la retirer. En 18 le modèle porte
-- `_auto = False` et `_table_query = '0'` : son nom n'entre plus dans
-- aucune requête, et registry.py exclut ces modèles du contrôle des
-- tables manquantes — Odoo ne la recréera donc jamais.
--
-- Elle n'est pas seulement morte, elle est FAUSSE : bâtie sur la colonne
-- `code` que l'ORM 18 n'écrit plus, elle rendait 14 racines là où la
-- donnée vivante (code_store) en portait 31. Un objet du schéma public
-- qui répond faux, sans avertir, à qui l'interroge à la main ou par un
-- outil décisionnel.
--
-- Elle est AUSSI l'unique épingle de deux colonnes héritées :
-- database_cleanup a purgé 110 colonnes orphelines au palier 18 et n'a
-- échoué que sur account_account.code et .company_id, dont elle dépend.
-- On retire donc l'obstacle ICI, et l'outil déjà en place finit sa passe
-- APRÈS le chargement en 18.
--
-- On ne supprime SURTOUT PAS les colonnes ici : le post-migration
-- d'OpenUpgrade les lit encore pour remplir code_store et company_ids,
-- et il tourne après ce fichier.
DO $$
DECLARE
    oid_vue oid;
    oid_table oid;
    nb_dependants int;
BEGIN
    SELECT c.oid INTO oid_vue
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'account_root'
       AND c.relkind = 'v';
    IF oid_vue IS NULL THEN
        -- Ni vue, ni base sans le module account : rien à faire. C'est
        -- aussi ce qui rend l'ordre rejouable après un premier passage.
        RETURN;
    END IF;

    oid_table := to_regclass('public.account_account');
    IF oid_table IS NULL THEN
        RAISE NOTICE 'account_root sans account_account : laissee en place';
        RETURN;
    END IF;

    -- La vue morte est CELLE QUI LIT account_account.code. Le contrôle
    -- est structurel et non textuel : si une version future d'Odoo
    -- recree un account_root d'une autre forme, on n'y touche pas.
    IF NOT EXISTS (
        SELECT 1
          FROM pg_depend d
          JOIN pg_rewrite r ON r.oid = d.objid
          JOIN pg_attribute a ON a.attrelid = d.refobjid
                             AND a.attnum = d.refobjsubid
         WHERE r.ev_class = oid_vue
           AND d.refobjid = oid_table
           AND a.attname = 'code'
    ) THEN
        RAISE NOTICE 'account_root ne lit pas account_account.code : laissee en place';
        RETURN;
    END IF;

    -- Rien ne doit en dependre. Le jour ou quelque chose en dependrait,
    -- APPRENDRE plutot que detruire : on le dit et on passe. Jamais de
    -- CASCADE, et jamais d echec — ce fichier tourne sous ON_ERROR_STOP.
    SELECT count(DISTINCT ev.oid) INTO nb_dependants
      FROM pg_depend d
      JOIN pg_rewrite r ON r.oid = d.objid
      JOIN pg_class ev ON ev.oid = r.ev_class
     WHERE d.refobjid = oid_vue
       AND ev.oid <> oid_vue;
    IF nb_dependants > 0 THEN
        RAISE NOTICE 'account_root : % objet(s) en dependent, laissee en place',
                     nb_dependants;
        RETURN;
    END IF;

    DROP VIEW public.account_root;
    RAISE NOTICE 'vue morte account_root supprimee (Odoo 18 ne la recree pas)';
END $$;
