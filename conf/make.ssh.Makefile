#######
# SSH #
#######

# Connection variables (override on command line or via environment)
SSH_HOST ?=
SSH_USER ?= erplibre
SSH_PORT ?= 22
SSH_KEY  ?=
SSH_PATH ?= ~/erplibre_deploy_2

# Target to run remotely via ssh_make
SSH_TARGET ?= run

# Build SSH/rsync options from variables
_SSH_KEY_OPT = $(if $(SSH_KEY),-i $(SSH_KEY),)
_SSH_CMD     = ssh -p $(SSH_PORT) -o StrictHostKeyChecking=accept-new $(_SSH_KEY_OPT)
_RSYNC_SSH   = ssh -p $(SSH_PORT) -o StrictHostKeyChecking=accept-new $(_SSH_KEY_OPT)

define _require_host
	@test -n "$(SSH_HOST)" || \
		(echo "Error: SSH_HOST is required. Usage: make $@ SSH_HOST=hostname [SSH_USER=erplibre] [SSH_PORT=22] [SSH_KEY=~/.ssh/id_rsa]" && exit 1)
endef

# Test SSH connectivity
.PHONY: ssh_check
ssh_check:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) "echo 'SSH connection to $(SSH_HOST) OK && uname -a'"

# Sync project files to remote (excludes venvs, addons, odoo sources, git)
.PHONY: ssh_push
ssh_push:
	$(call _require_host)
	rsync -avz --delete \
		--exclude='.venv.*/' \
		--exclude='addons/' \
		--exclude='odoo12.0/' \
		--exclude='odoo13.0/' \
		--exclude='odoo14.0/' \
		--exclude='odoo15.0/' \
		--exclude='odoo16.0/' \
		--exclude='odoo17.0/' \
		--exclude='odoo18.0/' \
		--exclude='.git/' \
		--exclude='private/' \
		--exclude='*.pyc' \
		--exclude='__pycache__/' \
		-e "$(_RSYNC_SSH)" \
		./ $(SSH_USER)@$(SSH_HOST):$(SSH_PATH)/

# Install ERPLibre on remote server (Odoo 18 default)
.PHONY: ssh_install
ssh_install:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) "cd $(SSH_PATH) && make install_odoo_18"

# Start Odoo on remote server
.PHONY: ssh_run
ssh_run:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) "cd $(SSH_PATH) && make run"

# Stop Odoo on remote server (via systemd if available, else kill process)
.PHONY: ssh_stop
ssh_stop:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) \
		"systemctl --user stop erplibre 2>/dev/null || \
		 sudo systemctl stop erplibre 2>/dev/null || \
		 cd $(SSH_PATH) && make process_kill_odoo"

# Restart Odoo on remote server
.PHONY: ssh_restart
ssh_restart:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) \
		"systemctl --user restart erplibre 2>/dev/null || \
		 sudo systemctl restart erplibre 2>/dev/null || \
		 (cd $(SSH_PATH) && make process_kill_odoo && make run)"

# Show service status on remote server
.PHONY: ssh_status
ssh_status:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) \
		"systemctl --user status erplibre 2>/dev/null || \
		 sudo systemctl status erplibre 2>/dev/null || \
		 ps aux | grep odoo | grep -v grep"

# Stream logs from remote server
.PHONY: ssh_logs
ssh_logs:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) \
		"journalctl --user -u erplibre -f 2>/dev/null || \
		 sudo journalctl -u erplibre -f"

# Execute any make target on remote server (e.g.: make ssh_make SSH_HOST=host SSH_TARGET=db_create_db_test)
.PHONY: ssh_make
ssh_make:
	$(call _require_host)
	@test -n "$(SSH_TARGET)" || \
		(echo "Error: SSH_TARGET is required. Usage: make ssh_make SSH_HOST=hostname SSH_TARGET=make_target" && exit 1)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) "cd $(SSH_PATH) && make $(SSH_TARGET)"

# Install systemd service on remote server
.PHONY: ssh_install_systemd
ssh_install_systemd:
	$(call _require_host)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) \
		"cd $(SSH_PATH) && python3 script/systemd/install_daemon.py \
		--user $(SSH_USER) \
		--home-erplibre $(SSH_PATH) \
		--port 8069"

# Configure nginx + SSL on remote server (requires SSH_DOMAIN)
SSH_DOMAIN    ?=
SSH_ADMIN_EMAIL ?=
.PHONY: ssh_install_nginx
ssh_install_nginx:
	$(call _require_host)
	@test -n "$(SSH_DOMAIN)" || \
		(echo "Error: SSH_DOMAIN is required. Usage: make ssh_install_nginx SSH_HOST=hostname SSH_DOMAIN=example.com [SSH_ADMIN_EMAIL=admin@example.com]" && exit 1)
	$(_SSH_CMD) $(SSH_USER)@$(SSH_HOST) \
		"cd $(SSH_PATH) && sudo python3 script/nginx/deploy_nginx_and_certbot.py \
		--generate_nginx \
		--run_certbot \
		--domain $(SSH_DOMAIN) \
		$(if $(SSH_ADMIN_EMAIL),--admin_email $(SSH_ADMIN_EMAIL),)"
