##############
# STREAMDECK #
##############

.PHONY: streamdeck
streamdeck:
	./script/stream_deck/erplibre_controller.py

.PHONY: streamdeck_snake
streamdeck_snake:
	./script/stream_deck/game_snake.py
