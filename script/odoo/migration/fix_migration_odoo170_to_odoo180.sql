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
