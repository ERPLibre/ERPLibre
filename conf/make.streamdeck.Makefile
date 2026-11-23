##############
# STREAMDECK #
##############

# Interpreter of the dedicated Stream Deck venv. Every deck entry point
# runs under it explicitly: a shebang cannot name a path relative to
# the checkout.
STREAMDECK_PY := .venv.streamdeck/bin/python

# A target that runs deck code lists $(STREAMDECK_PY) as a prerequisite.
# The file has no prerequisite of its own, so make runs this recipe only
# when the venv is missing, and the target stops there with the command
# that builds it.
$(STREAMDECK_PY):
	@echo "Stream Deck venv missing: make erplibre_home_streamdeck_install" >&2
	@exit 1

# The deck program is a separate repository, a Google Repo project at
# script/stream_deck/deck/: the Stream Deck level of the installer adds it
# to the local manifest and syncs it. Every deck entry point lives there.
# A target that runs one lists streamdeck_deck_present, which stops it,
# when the checkout is missing, with the command that installs it.
STREAMDECK_DECK := script/stream_deck/deck

.PHONY: streamdeck_deck_present
streamdeck_deck_present:
	@bash -c '. script/install/erplibre_home_settings.sh && \
		{ deck_repo_present || \
		{ deck_repo_absent_message >&2; exit 1; }; }'

# The GNOME extension is a separate repository, a Google Repo project at
# script/gnome-extension/erplibre_home/. A target that runs one of its
# files lists erplibre_home_extension_present, which stops it, when the
# checkout is missing, with the command that installs it. The targets that
# go through the installer need no guard: the installer syncs it.
.PHONY: erplibre_home_extension_present
erplibre_home_extension_present:
	@bash -c '. script/install/erplibre_home_settings.sh && \
		{ erplibre_home_extension_present || \
		{ erplibre_home_extension_absent_message >&2; exit 1; }; }'

.PHONY: streamdeck
streamdeck: $(STREAMDECK_PY) streamdeck_deck_present
	$(STREAMDECK_PY) $(STREAMDECK_DECK)/erplibre_controller.py

# The deck program of ERPLibre Home; streamdeck_tiler is its former name.
.PHONY: streamdeck_erplibre
streamdeck_erplibre: $(STREAMDECK_PY) streamdeck_deck_present
	$(STREAMDECK_PY) $(STREAMDECK_DECK)/erplibre_streamdeck

.PHONY: streamdeck_tiler
streamdeck_tiler: streamdeck_erplibre

# ERPLibre Home, two levels. The base: the GNOME extension, its schemas
# and translations, linked and enabled. The Stream Deck level adds the USB
# packages, the udev rule, the deck program checkout and .venv.streamdeck,
# and installs the base too.
# The installer holds every step; these targets only call it, so make and
# the installer cannot disagree.
.PHONY: erplibre_home_install
erplibre_home_install:
	./script/install/install_erplibre_home.sh

# Removes both levels, except the system packages.
.PHONY: erplibre_home_uninstall
erplibre_home_uninstall:
	./script/install/install_erplibre_home.sh --uninstall

.PHONY: erplibre_home_streamdeck_install
erplibre_home_streamdeck_install:
	./script/install/install_erplibre_home.sh --stream-deck

# Removes the udev rule and .venv.streamdeck only; the extension stays
# installed and enabled.
.PHONY: erplibre_home_streamdeck_uninstall
erplibre_home_streamdeck_uninstall:
	./script/install/install_erplibre_home.sh --uninstall --stream-deck

ERPLIBRE_HOME_EXT_UUID       := erplibre-home@technolibre.ca
ERPLIBRE_HOME_EXT_SRC        := script/gnome-extension/erplibre_home
ERPLIBRE_HOME_EXT_BASE_DIR   := $(HOME)/.local/share/gnome-shell/extensions
ERPLIBRE_HOME_EXT_DST        := $(ERPLIBRE_HOME_EXT_BASE_DIR)/$(ERPLIBRE_HOME_EXT_UUID)
ERPLIBRE_HOME_EXT_TMP_PREFIX := erplibre-home-reload-

.PHONY: erplibre_home_install_extension
erplibre_home_install_extension:
	@./script/install/install_erplibre_home.sh --extension-only
	@echo "Symlinked $(ERPLIBRE_HOME_EXT_DST) -> $(CURDIR)/$(ERPLIBRE_HOME_EXT_SRC)"
	@echo "Then: make erplibre_home_enable_extension (Wayland: then log out / log in to load it; X11: Alt+F2, r)"

.PHONY: erplibre_home_enable_extension
erplibre_home_enable_extension: erplibre_home_extension_present
	@# Wayland scans the extensions directory only at login, so a fresh
	@# symlink is unknown to the running Shell and `enable` fails; the
	@# helper then writes the setting the Shell reads at login.
	@if err=$$(gnome-extensions enable "$(ERPLIBRE_HOME_EXT_UUID)" 2>&1); then \
		gnome-extensions info "$(ERPLIBRE_HOME_EXT_UUID)" | grep -iE 'Activ|Enabled'; \
	else \
		printf '%s\n' "$$err" | head -n 1 >&2; \
		"$(ERPLIBRE_HOME_EXT_SRC)/tools/enable_next_login.py" "$(ERPLIBRE_HOME_EXT_UUID)"; \
	fi

.PHONY: erplibre_home_uninstall_extension
erplibre_home_uninstall_extension:
	-@gnome-extensions disable "$(ERPLIBRE_HOME_EXT_UUID)" 2>/dev/null || true
	@rm -rf "$(ERPLIBRE_HOME_EXT_DST)"
	@echo "Removed $(ERPLIBRE_HOME_EXT_DST)"
	@for d in "$(ERPLIBRE_HOME_EXT_BASE_DIR)"/$(ERPLIBRE_HOME_EXT_TMP_PREFIX)*@technolibre.ca; do \
		[ -d "$$d" ] || [ -L "$$d" ] || continue; \
		uuid=$$(basename "$$d"); \
		gnome-extensions disable "$$uuid" 2>/dev/null || true; \
		rm -rf "$$d"; \
		echo "Removed reload temp $$uuid"; \
	done
	@echo "Log out / log in to fully unload from gnome-shell."

# Launch a nested gnome-shell with the extension loaded in an
# isolated XDG sandbox. Lets the dev reload code freely without
# touching the parent Wayland session — close the window to wipe.
.PHONY: erplibre_home_dev_nested
erplibre_home_dev_nested: erplibre_home_extension_present
	@$(ERPLIBRE_HOME_EXT_SRC)/dev_nested.sh

# Headless-ish smoke test: launch a nested gnome-shell with the
# extension enabled and verify the D-Bus interface answers. Needs a
# Wayland host on the dev machine (skipped on bare CI).
.PHONY: erplibre_home_e2e_nested
erplibre_home_e2e_nested: erplibre_home_extension_present
	@$(ERPLIBRE_HOME_EXT_SRC)/test/e2e_nested.sh

# ---------- Translator stack (STT + LLM) ----------

WHISPER_CPP_DIR   := $(HOME)/.local/share/whisper.cpp
WHISPER_CPP_REPO  := https://github.com/ggerganov/whisper.cpp
# Override at the command line: WHISPER_MODEL=base make ...
WHISPER_MODEL     ?= tiny

.PHONY: streamdeck_translator_doctor
streamdeck_translator_doctor: $(STREAMDECK_PY) streamdeck_deck_present
	@$(STREAMDECK_PY) $(STREAMDECK_DECK)/translator_doctor.py

.PHONY: streamdeck_translator_test
streamdeck_translator_test: $(STREAMDECK_PY) streamdeck_deck_present
	@$(STREAMDECK_PY) $(STREAMDECK_DECK)/translator_test.py

# The deck repository's own tests, run from its root as its README says:
# the translator's alone, or the whole suite (streamdeck_tiler_unittest
# keeps its former name).
.PHONY: streamdeck_translator_unittest
streamdeck_translator_unittest: $(STREAMDECK_PY) streamdeck_deck_present
	@cd $(STREAMDECK_DECK) && $(abspath $(STREAMDECK_PY)) -m unittest \
		discover -s tests -p "test_*translator.py" -v

.PHONY: streamdeck_tiler_unittest
streamdeck_tiler_unittest: $(STREAMDECK_PY) streamdeck_deck_present
	@cd $(STREAMDECK_DECK) && $(abspath $(STREAMDECK_PY)) -m unittest \
		discover -s tests -v

.PHONY: streamdeck_translator_stream
streamdeck_translator_stream: $(STREAMDECK_PY) streamdeck_deck_present
	@$(STREAMDECK_PY) $(STREAMDECK_DECK)/translator_stream.py

.PHONY: streamdeck_translator_install_whisper
streamdeck_translator_install_whisper:
	@if [ ! -d "$(WHISPER_CPP_DIR)" ]; then \
		echo "Cloning whisper.cpp into $(WHISPER_CPP_DIR)..."; \
		git clone --depth 1 "$(WHISPER_CPP_REPO)" "$(WHISPER_CPP_DIR)"; \
	else \
		echo "whisper.cpp already at $(WHISPER_CPP_DIR), pulling..."; \
		git -C "$(WHISPER_CPP_DIR)" pull --ff-only || true; \
	fi
	@echo "Building whisper.cpp (this takes a few minutes)..."
	@$(MAKE) -C "$(WHISPER_CPP_DIR)" 2>&1 | tail -20
	@echo "Building whisper-stream binary..."
	@$(MAKE) -C "$(WHISPER_CPP_DIR)" stream 2>&1 | tail -10 || \
		echo "Note: stream target failed; live streaming will be unavailable."
	@echo "Downloading $(WHISPER_MODEL) model (~75 MB)..."
	@bash "$(WHISPER_CPP_DIR)/models/download-ggml-model.sh" \
		"$(WHISPER_MODEL)"
	@echo ""
	@echo "Done. Verify: make streamdeck_translator_doctor"

.PHONY: streamdeck_translator_install_ollama
streamdeck_translator_install_ollama: $(STREAMDECK_PY) streamdeck_deck_present
	@if command -v ollama >/dev/null 2>&1; then \
		echo "ollama already installed at $$(command -v ollama)"; \
	else \
		echo "About to run: curl -fsSL https://ollama.com/install.sh | sh"; \
		echo "This installs ollama as a systemd user service."; \
		printf "Continue? [y/N] "; read ans; \
		case "$$ans" in [yY]) ;; *) echo "Cancelled."; exit 1;; esac; \
		curl -fsSL https://ollama.com/install.sh | sh; \
	fi
	@model=$$($(STREAMDECK_PY) $(STREAMDECK_DECK)/translator_doctor.py --recommend); \
	echo ""; \
	echo "Pulling hardware-recommended model: $$model"; \
	ollama pull "$$model"
	@echo ""
	@echo "Done. Verify: make streamdeck_translator_doctor"

VOSK_CACHE_DIR    := $(HOME)/.cache/erplibre-home
VOSK_FR_URL       := https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip

.PHONY: streamdeck_translator_install_vosk_fr
streamdeck_translator_install_vosk_fr: $(STREAMDECK_PY)
	@echo "Installing Vosk Python package + French model..."
	@$(STREAMDECK_PY) -m pip install vosk
	@mkdir -p "$(VOSK_CACHE_DIR)"
	@curl -L "$(VOSK_FR_URL)" -o /tmp/vosk-fr.zip
	@unzip -oq /tmp/vosk-fr.zip -d "$(VOSK_CACHE_DIR)"
	@rm -rf "$(VOSK_CACHE_DIR)/vosk-model"
	@mv "$(VOSK_CACHE_DIR)"/vosk-model-small-fr-* \
		"$(VOSK_CACHE_DIR)/vosk-model"
	@rm -f /tmp/vosk-fr.zip
	@echo "Done. Verify: make streamdeck_translator_doctor"

.PHONY: streamdeck_translator_install_typing
streamdeck_translator_install_typing:
	@echo "Installing wl-clipboard + ydotool for Wayland output..."
	sudo apt install -y wl-clipboard ydotool
	@echo "Enabling ydotoold service..."
	sudo systemctl enable --now ydotoold
	@echo "Adding user to input group (re-login required)..."
	sudo usermod -aG input "$$USER"
	@echo ""
	@echo "Done. Re-login for the input group to take effect."
	@echo "Verify: make streamdeck_translator_doctor"

ERPLIBRE_HOME_DBUS_DEST    := org.gnome.Shell
ERPLIBRE_HOME_DBUS_PATH    := /org/gnome/Shell/Extensions/ERPLibreHome
ERPLIBRE_HOME_DBUS_IFACE   := org.gnome.Shell.Extensions.ERPLibreHome

# Hot-reload via the extension's own D-Bus HotReload method (UUID-rename
# trick performed from inside the shell JS context, where
# Main.extensionManager.createExtensionObject + loadExtension are
# accessible). Requires the extension's updated code to already be running
# — on first install, re-login once before using this target.
.PHONY: erplibre_home_reload
erplibre_home_reload: erplibre_home_install_extension
	@out=$$(gdbus call --session \
		--dest "$(ERPLIBRE_HOME_DBUS_DEST)" \
		--object-path "$(ERPLIBRE_HOME_DBUS_PATH)" \
		--method "$(ERPLIBRE_HOME_DBUS_IFACE).HotReload" 2>&1); \
	echo "$$out"; \
	case "$$out" in \
		"('',)"|*UnknownMethod*|*error*|*Erreur*) \
			echo ""; \
			echo "HotReload unavailable or returned empty."; \
			echo "First install requires one re-login to register the method."; \
			exit 1 ;; \
	esac; \
	echo "Hot-reloaded. Run erplibre_home_reload_clean (optionally after"; \
	echo "re-login) to restore the main UUID."

.PHONY: erplibre_home_reload_clean
erplibre_home_reload_clean:
	@# Best-effort call to HotExit (works only if a temp instance is running)
	-@gdbus call --session \
		--dest "$(ERPLIBRE_HOME_DBUS_DEST)" \
		--object-path "$(ERPLIBRE_HOME_DBUS_PATH)" \
		--method "$(ERPLIBRE_HOME_DBUS_IFACE).HotExit" 2>/dev/null || true
	@sleep 1
	@# Fallback: purge any leftover temp dirs on disk + re-enable main UUID
	@for d in "$(ERPLIBRE_HOME_EXT_BASE_DIR)"/$(ERPLIBRE_HOME_EXT_TMP_PREFIX)*@technolibre.ca; do \
		[ -d "$$d" ] || continue; \
		uuid=$$(basename "$$d"); \
		gnome-extensions disable "$$uuid" 2>/dev/null || true; \
		rm -rf "$$d"; \
		echo "Removed $$uuid"; \
	done
	@gnome-extensions enable "$(ERPLIBRE_HOME_EXT_UUID)" 2>/dev/null || true
	@echo "Re-enabled $(ERPLIBRE_HOME_EXT_UUID)."
	@echo "Before re-login: main UUID runs cached (old) code."
	@echo "After re-login:  main UUID loads the latest installed source."

# ---------- Claude Code hooks ----------

CLAUDE_HOOKS_INSTALLER := \
	$(ERPLIBRE_HOME_EXT_SRC)/hooks/install_claude_hooks.py

.PHONY: claude_install_hooks
claude_install_hooks: erplibre_home_extension_present
	@$(CLAUDE_HOOKS_INSTALLER)

.PHONY: claude_install_hooks_dry_run
claude_install_hooks_dry_run: erplibre_home_extension_present
	@$(CLAUDE_HOOKS_INSTALLER) --dry-run

.PHONY: claude_uninstall_hooks
claude_uninstall_hooks: erplibre_home_extension_present
	@$(CLAUDE_HOOKS_INSTALLER) --remove

# ---------- erplibre-home i18n ----------

.PHONY: erplibre_home_compile_locale
erplibre_home_compile_locale: erplibre_home_extension_present
	@python3 $(ERPLIBRE_HOME_EXT_SRC)/po/compile_locales.py
