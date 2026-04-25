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

STREAMDECK_TILER_EXT_UUID       := streamdeck-tiler@technolibre.ca
STREAMDECK_TILER_EXT_SRC        := script/stream_deck/gnome-extension
STREAMDECK_TILER_EXT_BASE_DIR   := $(HOME)/.local/share/gnome-shell/extensions
STREAMDECK_TILER_EXT_DST        := $(STREAMDECK_TILER_EXT_BASE_DIR)/$(STREAMDECK_TILER_EXT_UUID)
STREAMDECK_TILER_EXT_TMP_PREFIX := streamdeck-tiler-reload-

.PHONY: streamdeck_tiler_install_extension
streamdeck_tiler_install_extension:
	@mkdir -p "$(STREAMDECK_TILER_EXT_DST)"
	@cp "$(STREAMDECK_TILER_EXT_SRC)/extension.js" "$(STREAMDECK_TILER_EXT_DST)/"
	@cp "$(STREAMDECK_TILER_EXT_SRC)/metadata.json" "$(STREAMDECK_TILER_EXT_DST)/"
	@echo "Installed to $(STREAMDECK_TILER_EXT_DST)"
	@echo "Wayland: log out / log in to load new source (ES modules are cached)."
	@echo "X11:     press Alt+F2, type r, Enter."
	@echo "Then:    make streamdeck_tiler_enable_extension"

.PHONY: streamdeck_tiler_enable_extension
streamdeck_tiler_enable_extension:
	@gnome-extensions enable "$(STREAMDECK_TILER_EXT_UUID)"
	@gnome-extensions info "$(STREAMDECK_TILER_EXT_UUID)" | grep -iE 'Activ|Enabled'

.PHONY: streamdeck_tiler_uninstall_extension
streamdeck_tiler_uninstall_extension:
	-@gnome-extensions disable "$(STREAMDECK_TILER_EXT_UUID)" 2>/dev/null || true
	@rm -rf "$(STREAMDECK_TILER_EXT_DST)"
	@echo "Removed $(STREAMDECK_TILER_EXT_DST) (log out/in to fully unload)"

STREAMDECK_TILER_DBUS_DEST    := org.gnome.Shell
STREAMDECK_TILER_DBUS_PATH    := /org/gnome/Shell/Extensions/StreamDeckTiler
STREAMDECK_TILER_DBUS_IFACE   := org.gnome.Shell.Extensions.StreamDeckTiler

# Hot-reload via the extension's own D-Bus HotReload method (UUID-rename
# trick performed from inside the shell JS context, where
# Main.extensionManager.createExtensionObject + loadExtension are
# accessible). Requires the extension's updated code to already be running
# — on first install, re-login once before using this target.
.PHONY: streamdeck_tiler_reload
streamdeck_tiler_reload: streamdeck_tiler_install_extension
	@out=$$(gdbus call --session \
		--dest "$(STREAMDECK_TILER_DBUS_DEST)" \
		--object-path "$(STREAMDECK_TILER_DBUS_PATH)" \
		--method "$(STREAMDECK_TILER_DBUS_IFACE).HotReload" 2>&1); \
	echo "$$out"; \
	case "$$out" in \
		"('',)"|*UnknownMethod*|*error*|*Erreur*) \
			echo ""; \
			echo "HotReload unavailable or returned empty."; \
			echo "First install requires one re-login to register the method."; \
			exit 1 ;; \
	esac; \
	echo "Hot-reloaded. Run streamdeck_tiler_reload_clean (optionally after"; \
	echo "re-login) to restore the main UUID."

.PHONY: streamdeck_tiler_reload_clean
streamdeck_tiler_reload_clean:
	@# Best-effort call to HotExit (works only if a temp instance is running)
	-@gdbus call --session \
		--dest "$(STREAMDECK_TILER_DBUS_DEST)" \
		--object-path "$(STREAMDECK_TILER_DBUS_PATH)" \
		--method "$(STREAMDECK_TILER_DBUS_IFACE).HotExit" 2>/dev/null || true
	@sleep 1
	@# Fallback: purge any leftover temp dirs on disk + re-enable main UUID
	@for d in "$(STREAMDECK_TILER_EXT_BASE_DIR)"/$(STREAMDECK_TILER_EXT_TMP_PREFIX)*@technolibre.ca; do \
		[ -d "$$d" ] || continue; \
		uuid=$$(basename "$$d"); \
		gnome-extensions disable "$$uuid" 2>/dev/null || true; \
		rm -rf "$$d"; \
		echo "Removed $$uuid"; \
	done
	@gnome-extensions enable "$(STREAMDECK_TILER_EXT_UUID)" 2>/dev/null || true
	@echo "Re-enabled $(STREAMDECK_TILER_EXT_UUID)."
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
