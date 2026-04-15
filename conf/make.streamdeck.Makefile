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
