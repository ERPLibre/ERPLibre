#########
# Robot #
#########
.PHONY: robot_libre_all
robot_libre_all:
	echo "Install all for robot_libre"
	./script/make.sh robot_libre_init
	./script/make.sh robot_libre_pre
	OPEN_DASHBOARD=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops,erplibre_devops_me,erplibre_devops_extra

.PHONY: robot_libre_init
robot_libre_init:
	echo "Robot Libre init"
	echo "Sorry for your lost data"
	echo "Generate repository"
	#./script/manifest/update_manifest_local_dev.sh "-g base,image_db,code_generator"
	echo "Generate new fast configuration repo"
	#./script/git/git_repo_update_group.py --group base,code_generator
	echo "Generate configuration"
	#./script/generate_config.sh
	#./script/git/git_change_remote_https_to_git.py

.PHONY: robot_libre_pre
robot_libre_pre:
	echo "Create database robotlibre"
	./script/database/db_restore.py --database robotlibre

.PHONY: robot_libre
robot_libre:
	./script/make.sh robot_libre_pre
	echo "Install devops"
	./script/addons/install_addons_dev.sh robotlibre erplibre_devops
	./odoo_bin.sh db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_fast
robot_libre_fast:
	echo "FAST! RobotLibre"
	./odoo_bin.sh db --drop --database _cache_robotlibre_last
	./script/database/db_restore.py --database robotlibre --image robotlibre_last

.PHONY: robot_libre_fast_update
robot_libre_fast_update:
	echo "FAST! RobotLibre with update"
	./odoo_bin.sh db --drop --database _cache_robotlibre_last
	./script/database/db_restore.py --database robotlibre --image robotlibre_last
	./script/addons/install_addons_dev.sh robotlibre erplibre_devops

.PHONY: robot_libre_extra
robot_libre_extra:
	./script/make.sh robot_libre_pre
	echo "Install erplibre_devops and erplibre_devops_extra"
	./script/addons/install_addons_dev.sh robotlibre erplibre_devops,erplibre_devops_extra
	./odoo_bin.sh db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_me
robot_libre_me:
	./script/make.sh robot_libre_pre
	echo "Install erplibre_devops, erplibre_devops_me and erplibre_devops_extra"
	OPEN_DASHBOARD=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops,erplibre_devops_me,erplibre_devops_extra
	./odoo_bin.sh db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_me_only
robot_libre_me_only:
	./script/make.sh robot_libre
	IS_ONLY_ME=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me
	./odoo_bin.sh db --backup --database robotlibre --restore_image robotlibre_last

.PHONY: robot_libre_me_auto
robot_libre_me_auto:
	./script/make.sh robot_libre
	IS_ME_AUTO=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me

.PHONY: robot_libre_me_auto_force
robot_libre_me_auto_force:
	./script/make.sh robot_libre
	IS_ME_AUTO_FORCE=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me

.PHONY: robot_libre_me_only_auto_force
robot_libre_me_only_auto_force:
	./script/make.sh robot_libre
	IS_ONLY_ME=TRUE IS_ME_AUTO_FORCE=TRUE ./run.sh --dev cg -d robotlibre -i erplibre_devops_me

.PHONY: robot_libre_update
robot_libre_update:
	./run.sh --limit-time-real 999999 --no-http --stop-after-init --dev cg -d robotlibre -i erplibre_devops -u erplibre_devops

.PHONY: robot_libre_run
robot_libre_run:
	./run.sh -d robotlibre

.PHONY: robot_libre_open
robot_libre_open:
	./.venv/bin/python ./script/selenium/web_login.py

.PHONY: robot_libre_open_record
robot_libre_open_record:
	./.venv/bin/python ./script/selenium/web_login.py --record_mode

.PHONY: robot_libre_format
robot_libre_format:
	parallel ::: "./script/maintenance/format.sh ./addons/ERPLibre_erplibre_addons/erplibre_devops" "./script/maintenance/format.sh ./addons/ERPLibre_erplibre_addons/erplibre_devops_me"

.PHONY: robot_libre_generate
robot_libre_generate:
	./script/code_generator/new_project.py -f -d ./addons/ERPLibre_erplibre_addons -m erplibre_devops

.PHONY: run_db
run_db:
	./run.sh -d $(bd)
