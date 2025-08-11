import urwid


def show_main_menu():
    """Builds and displays the main menu with 5 questions."""
    menu_widgets = [
        urwid.Text(("bold", "Menu principal")),
        urwid.Divider(),
        urwid.Button(
            "Question 1: Quel est votre langage de programmation préféré?",
            on_press_question_1,
        ),
        urwid.Button(
            "Question 2: Quel est votre système d'exploitation?",
            on_press_question_2,
        ),
        urwid.Button(
            "Question 3: À quoi sert le module 'os' en Python?",
            on_press_question_3,
        ),
        urwid.Button(
            "Question 4: Quelle est la différence entre une liste et un tuple?",
            on_press_question_4,
        ),
        urwid.Button(
            "Question 5: Comment gérer les erreurs en Python?",
            on_press_question_5,
        ),
        urwid.Divider(),
        urwid.Button("Quitter", exit_program),
    ]

    menu_listbox = urwid.ListBox(urwid.SimpleFocusListWalker(menu_widgets))

    # Corrected part: The Filler needs a widget that has a 'rows' attribute, which ListBox does not.
    # The ListBox is a 'flow' widget; it flows to fit its content.
    # To use it in a filler, it needs to be wrapped inside a 'box' widget.
    # The simplest way to achieve this is to just remove the filler, as the MainLoop handles sizing,
    # but for a more robust design, you can use a Frame or other box widget.
    # Let's remove the Filler, since the MainLoop can handle the ListBox directly.
    return menu_listbox


def show_sub_menu(question_title, sub_questions, back_to_main_menu_func):
    """Builds and displays a sub-menu for a specific question."""
    sub_menu_widgets = [
        urwid.Text(("bold", question_title)),
        urwid.Divider(),
    ]
    for sub_question in sub_questions:
        sub_menu_widgets.append(urwid.Button(sub_question))

    sub_menu_widgets.extend(
        [
            urwid.Divider(),
            urwid.Button("Retour au menu principal", back_to_main_menu_func),
        ]
    )

    sub_menu_listbox = urwid.ListBox(
        urwid.SimpleFocusListWalker(sub_menu_widgets)
    )

    # We remove the filler here as well for consistency.
    return sub_menu_listbox


def exit_program(button):
    """Exits the application."""
    raise urwid.ExitMainLoop()


def on_press_question_1(button):
    """Callback for Question 1."""
    sub_questions = [
        "Sous-question 1.1: Pourquoi le C++ est-il populaire pour les jeux?",
        "Sous-question 1.2: Quel est l'avantage principal de JavaScript?",
        "Sous-question 1.3: Qu'est-ce qui rend Python si polyvalent?",
    ]
    sub_menu = show_sub_menu(
        "Sous-questions de la Question 1", sub_questions, back_to_main_menu
    )
    loop.widget = sub_menu


def on_press_question_2(button):
    """Callback for Question 2."""
    sub_questions = [
        "Sous-question 2.1: Quels sont les avantages de Linux?",
        "Sous-question 2.2: Pourquoi Windows est-il si répandu?",
        "Sous-question 2.3: Quels sont les points forts de macOS?",
    ]
    sub_menu = show_sub_menu(
        "Sous-questions de la Question 2", sub_questions, back_to_main_menu
    )
    loop.widget = sub_menu


def on_press_question_3(button):
    """Callback for Question 3."""
    sub_questions = [
        "Sous-question 3.1: Comment lister les fichiers d'un répertoire?",
        "Sous-question 3.2: Comment créer un nouveau dossier?",
        "Sous-question 3.3: Comment supprimer un fichier?",
    ]
    sub_menu = show_sub_menu(
        "Sous-questions de la Question 3", sub_questions, back_to_main_menu
    )
    loop.widget = sub_menu


def on_press_question_4(button):
    """Callback for Question 4."""
    sub_questions = [
        "Sous-question 4.1: Sont-ils mutables?",
        "Sous-question 4.2: Quelle est leur syntaxe respective?",
        "Sous-question 4.3: Quand utiliser l'un plutôt que l'autre?",
    ]
    sub_menu = show_sub_menu(
        "Sous-questions de la Question 4", sub_questions, back_to_main_menu
    )
    loop.widget = sub_menu


def on_press_question_5(button):
    """Callback for Question 5."""
    sub_questions = [
        "Sous-question 5.1: Quel est le rôle des blocs 'try' et 'except'?",
        "Sous-question 5.2: À quoi sert le mot-clé 'finally'?",
        "Sous-question 5.3: Comment lever une exception personnalisée?",
    ]
    sub_menu = show_sub_menu(
        "Sous-questions de la Question 5", sub_questions, back_to_main_menu
    )
    loop.widget = sub_menu


def back_to_main_menu(button):
    """Returns to the main menu."""
    loop.widget = show_main_menu()


# Define color schemes
palette = [
    ("header", "dark cyan", "black"),
    ("footer", "dark cyan", "black"),
    ("body", "white", "black"),
    ("button", "black", "dark cyan", "standout"),
    ("focus", "white", "dark green", "bold"),
    ("bold", "bold", "black"),
]

# Create the main menu widget
main_menu_widget = show_main_menu()

# Set up the main loop with the menu
loop = urwid.MainLoop(
    main_menu_widget,
    palette,
    unhandled_input=exit_program,
)

# Run the application
loop.run()
