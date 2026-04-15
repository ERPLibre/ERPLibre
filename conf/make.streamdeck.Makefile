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

.PHONY: streamdeck_pongplus
streamdeck_pongplus:
	./script/stream_deck/game_pongplus.py
