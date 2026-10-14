##############
# STREAMDECK #
##############

.PHONY: streamdeck
streamdeck:
	./script/stream_deck/erplibre_controller.py

.PHONY: streamdeck_snake
streamdeck_snake:
	./script/stream_deck/game_snake.py

.PHONY: streamdeck_minesweeper
streamdeck_minesweeper:
	./script/stream_deck/game_minesweeper.py

.PHONY: streamdeck_whackamole
streamdeck_whackamole:
	./script/stream_deck/game_whackamole.py

.PHONY: streamdeck_simon
streamdeck_simon:
	./script/stream_deck/game_simon.py

.PHONY: streamdeck_lightsout
streamdeck_lightsout:
	./script/stream_deck/game_lightsout.py

.PHONY: streamdeck_reaction
streamdeck_reaction:
	./script/stream_deck/game_reaction.py

.PHONY: streamdeck_breakout
streamdeck_breakout:
	./script/stream_deck/game_breakout.py

.PHONY: streamdeck_2048
streamdeck_2048:
	./script/stream_deck/game_2048.py

.PHONY: streamdeck_colormatch
streamdeck_colormatch:
	./script/stream_deck/game_colormatch.py

.PHONY: streamdeck_life
streamdeck_life:
	./script/stream_deck/game_life.py

.PHONY: streamdeck_taquin
streamdeck_taquin:
	./script/stream_deck/game_taquin.py

.PHONY: streamdeck_mastermind
streamdeck_mastermind:
	./script/stream_deck/game_mastermind.py

.PHONY: streamdeck_battleship
streamdeck_battleship:
	./script/stream_deck/game_battleship.py

.PHONY: streamdeck_flappy
streamdeck_flappy:
	./script/stream_deck/game_flappy.py

.PHONY: streamdeck_pong
streamdeck_pong:
	./script/stream_deck/game_pong.py

.PHONY: streamdeck_sokoban
streamdeck_sokoban:
	./script/stream_deck/game_sokoban.py

.PHONY: streamdeck_floodfill
streamdeck_floodfill:
	./script/stream_deck/game_floodfill.py

.PHONY: streamdeck_bomberman
streamdeck_bomberman:
	./script/stream_deck/game_bomberman.py

.PHONY: streamdeck_tictactoe
streamdeck_tictactoe:
	./script/stream_deck/game_tictactoe.py

# Stream Deck + games (dials + touchscreen)

.PHONY: streamdeck_safecracker
streamdeck_safecracker:
	./script/stream_deck/game_safecracker.py

.PHONY: streamdeck_slots
streamdeck_slots:
	./script/stream_deck/game_slots.py

.PHONY: streamdeck_colormixer
streamdeck_colormixer:
	./script/stream_deck/game_colormixer.py

.PHONY: streamdeck_djscratch
streamdeck_djscratch:
	./script/stream_deck/game_djscratch.py

.PHONY: streamdeck_tiler
streamdeck_tiler:
	./script/stream_deck/game_tiler.py

ERPLIBRE_HOME_EXT_UUID       := erplibre-home@technolibre.ca
ERPLIBRE_HOME_EXT_SRC        := script/gnome-extension/erplibre_home
ERPLIBRE_HOME_EXT_BASE_DIR   := $(HOME)/.local/share/gnome-shell/extensions
ERPLIBRE_HOME_EXT_DST        := $(ERPLIBRE_HOME_EXT_BASE_DIR)/$(ERPLIBRE_HOME_EXT_UUID)
ERPLIBRE_HOME_EXT_TMP_PREFIX := erplibre-home-reload-

.PHONY: erplibre_home_install_extension
erplibre_home_install_extension:
	@"$(ERPLIBRE_HOME_EXT_SRC)/tools/migrate_legacy.py" || echo "legacy migration did not run" >&2
	@if [ -L "$(ERPLIBRE_HOME_EXT_DST)" ] || [ -d "$(ERPLIBRE_HOME_EXT_DST)" ]; then \
		rm -rf "$(ERPLIBRE_HOME_EXT_DST)"; \
	fi
	@mkdir -p "$(ERPLIBRE_HOME_EXT_BASE_DIR)"
	@ln -sfn "$(CURDIR)/$(ERPLIBRE_HOME_EXT_SRC)" "$(ERPLIBRE_HOME_EXT_DST)"
	@glib-compile-schemas "$(ERPLIBRE_HOME_EXT_SRC)/schemas/" 2>/dev/null || true
	@python3 "$(ERPLIBRE_HOME_EXT_SRC)/po/compile_locales.py" 2>/dev/null \
		|| echo "(locale compile skipped — install python3-polib for translations)"
	@echo "Symlinked $(ERPLIBRE_HOME_EXT_DST) -> $(CURDIR)/$(ERPLIBRE_HOME_EXT_SRC)"
	@echo "Wayland: log out / log in to load new source (ES modules are cached)."
	@echo "X11:     press Alt+F2, type r, Enter."
	@echo "Then:    make erplibre_home_enable_extension"

.PHONY: erplibre_home_enable_extension
erplibre_home_enable_extension:
	@gnome-extensions enable "$(ERPLIBRE_HOME_EXT_UUID)"
	@gnome-extensions info "$(ERPLIBRE_HOME_EXT_UUID)" | grep -iE 'Activ|Enabled'

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

# Convenience aliases for the common short names users actually type.
.PHONY: erplibre_home_uninstall
erplibre_home_uninstall: erplibre_home_uninstall_extension

# Launch a nested gnome-shell with the extension loaded in an
# isolated XDG sandbox. Lets the dev reload code freely without
# touching the parent Wayland session — close the window to wipe.
.PHONY: erplibre_home_dev_nested
erplibre_home_dev_nested:
	@$(ERPLIBRE_HOME_EXT_SRC)/dev_nested.sh

# Headless-ish smoke test: launch a nested gnome-shell with the
# extension enabled and verify the D-Bus interface answers. Needs a
# Wayland host on the dev machine (skipped on bare CI).
.PHONY: erplibre_home_e2e_nested
erplibre_home_e2e_nested:
	@$(ERPLIBRE_HOME_EXT_SRC)/test/e2e_nested.sh

# ---------- Translator stack (STT + LLM) ----------

WHISPER_CPP_DIR   := $(HOME)/.local/share/whisper.cpp
WHISPER_CPP_REPO  := https://github.com/ggerganov/whisper.cpp
# Override at the command line: WHISPER_MODEL=base make ...
WHISPER_MODEL     ?= tiny

.PHONY: streamdeck_translator_doctor
streamdeck_translator_doctor:
	@./script/stream_deck/translator_doctor.py

.PHONY: streamdeck_translator_test
streamdeck_translator_test:
	@./script/stream_deck/translator_test.py

.PHONY: streamdeck_translator_unittest
streamdeck_translator_unittest:
	@python3 -m unittest \
		discover -s ./script/stream_deck -p "test_translator.py" -v

.PHONY: streamdeck_tiler_unittest
streamdeck_tiler_unittest:
	@python3 -m unittest \
		discover -s ./script/stream_deck -p "test_game_tiler*.py" -v

.PHONY: streamdeck_translator_stream
streamdeck_translator_stream:
	@./script/stream_deck/translator_stream.py

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
streamdeck_translator_install_ollama:
	@if command -v ollama >/dev/null 2>&1; then \
		echo "ollama already installed at $$(command -v ollama)"; \
	else \
		echo "About to run: curl -fsSL https://ollama.com/install.sh | sh"; \
		echo "This installs ollama as a systemd user service."; \
		printf "Continue? [y/N] "; read ans; \
		case "$$ans" in [yY]) ;; *) echo "Cancelled."; exit 1;; esac; \
		curl -fsSL https://ollama.com/install.sh | sh; \
	fi
	@model=$$(./script/stream_deck/translator_doctor.py --recommend); \
	echo ""; \
	echo "Pulling hardware-recommended model: $$model"; \
	ollama pull "$$model"
	@echo ""
	@echo "Done. Verify: make streamdeck_translator_doctor"

VOSK_CACHE_DIR    := $(HOME)/.cache/erplibre-home
VOSK_FR_URL       := https://alphacephei.com/vosk/models/vosk-model-small-fr-0.22.zip

.PHONY: streamdeck_translator_install_vosk_fr
streamdeck_translator_install_vosk_fr:
	@echo "Installing Vosk Python package + French model..."
	@pip install --user vosk
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

.PHONY: streamdeck_fishing
streamdeck_fishing:
	./script/stream_deck/game_fishing.py

.PHONY: streamdeck_maze
streamdeck_maze:
	./script/stream_deck/game_maze.py

.PHONY: streamdeck_tetris
streamdeck_tetris:
	./script/stream_deck/game_tetris.py

.PHONY: streamdeck_connect4
streamdeck_connect4:
	./script/stream_deck/game_connect4.py

.PHONY: streamdeck_spaceinvaders
streamdeck_spaceinvaders:
	./script/stream_deck/game_spaceinvaders.py

.PHONY: streamdeck_frogger
streamdeck_frogger:
	./script/stream_deck/game_frogger.py

.PHONY: streamdeck_hangman
streamdeck_hangman:
	./script/stream_deck/game_hangman.py

.PHONY: streamdeck_rps
streamdeck_rps:
	./script/stream_deck/game_rps.py

.PHONY: streamdeck_numberguess
streamdeck_numberguess:
	./script/stream_deck/game_numberguess.py

.PHONY: streamdeck_reversi
streamdeck_reversi:
	./script/stream_deck/game_reversi.py

.PHONY: streamdeck_langton
streamdeck_langton:
	./script/stream_deck/game_langton.py

.PHONY: streamdeck_piano
streamdeck_piano:
	./script/stream_deck/game_piano.py

.PHONY: streamdeck_thermometer
streamdeck_thermometer:
	./script/stream_deck/game_thermometer.py

.PHONY: streamdeck_wordle
streamdeck_wordle:
	./script/stream_deck/game_wordle.py

.PHONY: streamdeck_sudoku
streamdeck_sudoku:
	./script/stream_deck/game_sudoku.py

.PHONY: streamdeck_pacman
streamdeck_pacman:
	./script/stream_deck/game_pacman.py

.PHONY: streamdeck_checkers
streamdeck_checkers:
	./script/stream_deck/game_checkers.py

.PHONY: streamdeck_towerdefense
streamdeck_towerdefense:
	./script/stream_deck/game_towerdefense.py

.PHONY: streamdeck_racer
streamdeck_racer:
	./script/stream_deck/game_racer.py

.PHONY: streamdeck_dragrace
streamdeck_dragrace:
	./script/stream_deck/game_dragrace.py

.PHONY: streamdeck_racingplus
streamdeck_racingplus:
	./script/stream_deck/game_racingplus.py

.PHONY: streamdeck_pinball
streamdeck_pinball:
	./script/stream_deck/game_pinball.py

.PHONY: streamdeck_gallery
streamdeck_gallery:
	./script/stream_deck/gallery_server.py

# ---------- Claude Code hooks ----------

CLAUDE_HOOKS_INSTALLER := \
	$(ERPLIBRE_HOME_EXT_SRC)/hooks/install_claude_hooks.py

.PHONY: claude_install_hooks
claude_install_hooks:
	@$(CLAUDE_HOOKS_INSTALLER)

.PHONY: claude_install_hooks_dry_run
claude_install_hooks_dry_run:
	@$(CLAUDE_HOOKS_INSTALLER) --dry-run

.PHONY: claude_uninstall_hooks
claude_uninstall_hooks:
	@$(CLAUDE_HOOKS_INSTALLER) --remove

# ---------- erplibre-home i18n ----------

.PHONY: erplibre_home_compile_locale
erplibre_home_compile_locale:
	@python3 $(ERPLIBRE_HOME_EXT_SRC)/po/compile_locales.py
