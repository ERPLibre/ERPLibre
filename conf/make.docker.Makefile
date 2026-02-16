##########
# DOCKER #
##########

# run docker
.PHONY: docker_run
docker_run:
	docker compose up

.PHONY: docker_run_daemon
docker_run_daemon:
	docker compose up -d

.PHONY: docker_stop
docker_stop:
	docker compose down

.PHONY: docker_restart_daemon
docker_restart_daemon:
	./script/make.sh docker_stop
	./script/make.sh docker_run_daemon

.PHONY: docker_show_databases
docker_show_databases:
	./script/docker/docker_list_database.sh

.PHONY: docker_show_logs_live
docker_show_logs_live:
	docker compose logs -f

.PHONY: docker_show_process
docker_show_process:
	docker compose ps

.PHONY: docker_exec_erplibre
docker_exec_erplibre:
	./script/docker/docker_exec.sh

.PHONY: docker_exec_erplibre_gen_config
docker_exec_erplibre_gen_config:
	./script/docker/docker_gen_config.sh

.PHONY: docker_exec_erplibre_make_test
docker_exec_erplibre_make_test:
	./script/docker/docker_make_test.sh

.PHONY: docker_exec_erplibre_repo_show_status
docker_exec_erplibre_repo_show_status:
	./script/docker/docker_repo_show_status.sh

# build docker
.PHONY: docker_build_odoo_18
docker_build_odoo_18:
	./script/docker/docker_build.sh --odoo_18

.PHONY: docker_build_odoo_17
docker_build_odoo_17:
	./script/docker/docker_build.sh --odoo_17

.PHONY: docker_build_odoo_18
docker_build_odoo_18:
	./script/docker/docker_build.sh --odoo_16

.PHONY: docker_build_odoo_18_clean
docker_build_odoo_18_clean:
	./script/docker/docker_build.sh --odoo_16 --no-cache

.PHONY: docker_build_odoo_15
docker_build_odoo_15:
	./script/docker/docker_build.sh --odoo_15

.PHONY: docker_build_odoo_14
docker_build_odoo_14:
	./script/docker/docker_build.sh --odoo_14

.PHONY: docker_build_odoo_14_clean
docker_build_odoo_14_clean:
	./script/docker/docker_build.sh --odoo_14 --no-cache

.PHONY: docker_build_odoo_13
docker_build_odoo_13:
	./script/docker/docker_build.sh --odoo_13

.PHONY: docker_build_odoo_12
docker_build_odoo_12:
	./script/docker/docker_build.sh --odoo_12

.PHONY: docker_build_odoo_12_clean
docker_build_odoo_12_clean:
	./script/docker/docker_build.sh --odoo_12 --no-cache

# build docker release
.PHONY: docker_build_release
docker_build_release:
	./script/docker/docker_build.sh --release

# build docker release alpha
.PHONY: docker_build_release_alpha
docker_build_release_alpha:
	./script/docker/docker_build.sh --release_alpha

# build docker release beta
.PHONY: docker_build_release_beta
docker_build_release_beta:
	./script/docker/docker_build.sh --release_beta

# docker clean all
.PHONY: docker_clean_all
docker_clean_all:
	./script/terminal/validate_to_continue.sh "⚠️ This will REMOVE unused images, containers, networks, and VOLUMES." && docker system prune -a --volumes

.PHONY: docker_compose_clean_all
docker_compose_clean_all:
	./script/terminal/validate_to_continue.sh "⚠️ This will REMOVE docker compose images, volumes and network." && docker compose down --rmi all -v
