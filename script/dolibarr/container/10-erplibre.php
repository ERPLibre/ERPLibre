<?php
/* © 2026 TechnoLibre (http://www.technolibre.ca)
 * License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
 *
 * Crochet de première installation de l'image officielle de Dolibarr.
 *
 * docker-run.sh le joue depuis /var/www/scripts/docker-init.d, une seule
 * fois, en root et en PHP CLI, APRÈS docker-init.php (modules de
 * DOLI_ENABLE_MODULES) et après sa propre mise à jour de CRON_KEY, vide
 * puisque DOLI_CRON_KEY n'est pas donné. Il ferme ce que l'installation
 * automatique de l'image laisse ouvert :
 * - hachage des mots de passe : DATABASE_PWD_ENCRYPTED=1 et
 *   MAIN_SECURITY_HASH_ALGO=password_hash, puis le mot de passe de
 *   l'administrateur est haché de nouveau (l'image le range en md5 sans
 *   sel, et tout changement ultérieur partirait en clair) ;
 * - CRON_KEY : lue dans /run/secrets/cron_key. L'entrée de l'image écrit
 *   dans ses journaux la clé qu'on lui donne ; ici elle n'y passe jamais.
 *   dolibarr_set_const() chiffre les constantes *_KEY avec
 *   $dolibarr_main_instance_unique_id : tout conteneur qui la lit reçoit
 *   le même DOLI_INSTANCE_UNIQUE_ID_FILE.
 *
 * N'affiche qu'un état, jamais un secret. Sort en 1 sur un échec ;
 * docker-run.sh ignore ce code, la ligne de fin dans les journaux du
 * conteneur fait foi. Rejouable : relancé à la main, il pose les mêmes
 * valeurs, ce qui sert aussi à changer la clé.
 */
require_once '/var/www/html/master.inc.php';
require_once DOL_DOCUMENT_ROOT.'/core/lib/admin.lib.php';
require_once DOL_DOCUMENT_ROOT.'/user/class/user.class.php';

$fail = 0;

foreach (array(
	'DATABASE_PWD_ENCRYPTED' => '1',
	'MAIN_SECURITY_HASH_ALGO' => 'password_hash',
) as $name => $value) {
	if (dolibarr_set_const($db, $name, $value, 'chaine', 0, '', 0) < 0) {
		$fail++;
	}
}

$login = getenv('DOLI_ADMIN_LOGIN') ?: 'admin';
$file = getenv('DOLI_ADMIN_PASSWORD_FILE');
$password = $file ? trim((string) @file_get_contents($file)) : '';
$admin = new User($db);
$res = -1;
if ($password !== '' && $admin->fetch(0, $login) > 0) {
	$res = $admin->setPassword($admin, $password, 0, 1);
}
if (is_int($res) && $res < 0) {
	print "erplibre hook: admin password NOT re-hashed\n";
	$fail++;
}

// Sans DOLI_ENABLE_MODULES=Cron, le module n'est pas actif : la ligne
// CRON_KEY n'existe pas encore.
if (!isModEnabled('cron') && activateModule('modCron') < 0) {
	$fail++;
}
$key = trim((string) @file_get_contents('/run/secrets/cron_key'));
if (!preg_match('/^[A-Za-z0-9]+$/', $key)) {
	print "erplibre hook: /run/secrets/cron_key missing or not alphanumeric\n";
	$fail++;
} elseif (dolibarr_set_const($db, 'CRON_KEY', $key, 'chaine', 0, '', 0) < 0) {
	$fail++;
}

print "erplibre hook: done; failures=".$fail."\n";
exit($fail ? 1 : 0);
