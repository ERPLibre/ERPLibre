-- © 2021-2026 TechnoLibre (http://www.technolibre.ca)
-- License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
--
-- Correctifs à appliquer AVANT qu'OpenUpgrade ne migre vers Odoo 13.
--
-- En SQL et non en Python : ce fichier tourne sur une base encore en 12,
-- que le code de la 13 ne saurait pas charger.

-- Ancres de page encodées en pourcentage.
--
-- Le script d'OpenUpgrade `website/migrations/13.0.1.0/post-migration.py`
-- ramasse les `href` des ancres d'une page et les RECOLLE en sélecteur CSS :
--
--     links = doc.cssselect(r"a[href^=\#]:not([href=\#])")
--     "selector": ", ".join([link.attrib["href"] for link in links])
--
-- Or un `href` n'est pas un sélecteur. Une ancre française encodée —
-- `#principes-mn%C3%A9moniques` — y introduit un `%`, interdit dans un
-- identifiant CSS, et la migration meurt :
--
--     cssselect.parser.SelectorSyntaxError: Expected selector, got <DELIM '%'>
--
-- Éprouvé avec le parseur d'Odoo 13 : `#principes-mnémoniques` passe,
-- `#principes-mn%C3%A9moniques` non. Décoder suffit donc, et un accent
-- reste un identifiant CSS valide.
--
-- On ne touche QUE les vues qu'OpenUpgrade parcourt — celles qui portent
-- une page — et QUE les `href` d'ancre. Un `%` ailleurs dans une URL est
-- légitime et reste intact.
--
-- Rejouable : une fois décodé il n'y a plus de `%XX` à trouver.

-- Le décodeur vit dans `pg_temp` : il disparaît avec la session psql, et
-- ne laisse rien derrière lui dans la base du client.
CREATE FUNCTION pg_temp.el_url_decode(entree text) RETURNS text AS $decode$
DECLARE
    octets bytea = '';
    morceau text;
BEGIN
    -- Deux à deux : « %C3 » devient un octet, tout autre caractère se
    -- recopie tel quel. On rassemble en bytea AVANT de convertir, car un
    -- caractère accenté tient sur deux octets et les décoder séparément
    -- rendrait deux caractères illisibles.
    FOR morceau IN
        SELECT (regexp_matches(entree, '(%[0-9A-Fa-f]{2}|.)', 'g'))[1]
    LOOP
        IF length(morceau) = 3 AND left(morceau, 1) = '%' THEN
            octets = octets || decode(substring(morceau, 2, 2), 'hex');
        ELSE
            octets = octets || convert_to(morceau, 'UTF8');
        END IF;
    END LOOP;
    RETURN convert_from(octets, 'UTF8');
END
$decode$ LANGUAGE plpgsql IMMUTABLE STRICT;

DO $$
DECLARE
    ancre RECORD;
    combien integer := 0;
BEGIN
    IF to_regclass('ir_ui_view') IS NULL THEN
        RETURN;
    END IF;
    FOR ancre IN
        SELECT DISTINCT trouve[1] AS brut
        FROM ir_ui_view v
        JOIN website_page p ON p.view_id = v.id,
             LATERAL regexp_matches(
                 v.arch_db, 'href="(#[^"]*%[0-9A-Fa-f]{2}[^"]*)"', 'g'
             ) AS trouve
    LOOP
        UPDATE ir_ui_view
        SET arch_db = replace(
                arch_db,
                'href="' || ancre.brut || '"',
                'href="' || pg_temp.el_url_decode(ancre.brut) || '"'
            )
        WHERE position('href="' || ancre.brut || '"' IN arch_db) > 0;
        combien := combien + 1;
        RAISE NOTICE 'ancre decodee : % -> %',
            ancre.brut, pg_temp.el_url_decode(ancre.brut);
    END LOOP;
    IF combien > 0 THEN
        RAISE NOTICE '% ancre(s) de page decodee(s)', combien;
    END IF;
END $$;
