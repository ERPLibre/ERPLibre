# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les chaînes du noyau, en français et en anglais.

Une entrée par clé, `{"fr": …, "en": …}`, les deux non vides. Le client
courriel ajoute ces entrées à son propre catalogue : une clé ne s'écrit
qu'ici. Une chaîne lue par le noyau s'écrit ici et jamais dans le
catalogue du client.
"""

CATALOG: dict[str, dict[str, str]] = {
    "mail_err_token_refused": {
        "fr": "jeton refusé par",
        "en": "token refused by",
    },
    "mail_err_unterminated_ampersand": {
        "fr": "séquence & non terminée",
        "en": "unterminated & sequence",
    },
    "mail_err_server_replied": {
        "fr": ": le serveur a répondu",
        "en": ": the server replied",
    },
    "mail_err_claim_read_only": {
        "fr": "boîte de réception en lecture seule : revendication impossible pour l'instant",
        "en": "inbox is read-only: claim impossible for now",
    },
    "mail_err_smtp_connection_prefix": {
        "fr": "connexion SMTP à",
        "en": "SMTP connection to",
    },
    "mail_err_connection_refused_suffix": {
        "fr": "refusée :",
        "en": "refused:",
    },
    "mail_tls_refused": {
        "fr": "certificat TLS refusé pour",
        "en": "TLS certificate refused for",
    },
    "mail_tls_changed": {
        "fr": "certificat TLS changé pour",
        "en": "TLS certificate changed for",
    },
    "mail_tls_presented": {
        "fr": "empreinte SHA-256 présentée :",
        "en": "presented SHA-256 fingerprint:",
    },
    "mail_tls_pinned": {
        "fr": "empreinte SHA-256 épinglée :",
        "en": "pinned SHA-256 fingerprint:",
    },
    "mail_tls_fingerprint_unreadable": {
        "fr": "illisible",
        "en": "unreadable",
    },
    "mail_tls_reason_untrusted": {
        "fr": "certificat auto-signé ou émis par une autorité inconnue",
        "en": "self-signed certificate or issued by an unknown authority",
    },
    "mail_tls_reason_hostname": {
        "fr": "le certificat ne porte pas ce nom de serveur",
        "en": "the certificate does not carry this server name",
    },
    "mail_tls_reason_validity": {
        "fr": "certificat expiré ou pas encore valide",
        "en": "certificate expired or not yet valid",
    },
    "mail_tls_reason_changed": {
        "fr": "certificat différent de celui qui est épinglé",
        "en": "certificate different from the pinned one",
    },
    "mail_tls_reason_nonconforming": {
        "fr": "certificat non conforme aux règles X.509 strictes de ce poste",
        "en": "certificate not conforming to this machine's strict X.509 rules",
    },
    "mail_err_reply_envelope_mismatch": {
        "fr": "réponse non construite : l'adresse cible ne se relit pas telle quelle dans l'en-tête To.",
        "en": "reply not built: the target address does not read back unchanged in the To header.",
    },
    "mail_err_message_needs_recipient": {
        "fr": "un message doit avoir au moins un destinataire",
        "en": "a message must have at least one recipient",
    },
    "mail_err_attachment_missing": {
        "fr": "pièce jointe introuvable :",
        "en": "attachment not found:",
    },
    "mail_err_no_recipient_nothing_sent": {
        "fr": "aucun destinataire : rien n'a été envoyé",
        "en": "no recipient: nothing was sent",
    },
    "mail_err_send_refused": {"fr": "envoi refusé :", "en": "send refused:"},
    "mail_err_inline_needs_html": {
        "fr": "Une image en ligne exige un corps HTML.",
        "en": "An inline image requires an HTML body.",
    },
    "mail_err_header_forbidden": {
        "fr": "En-tête réservé :",
        "en": "Reserved header:",
    },
    "mail_err_header_newline": {
        "fr": "Saut de ligne interdit dans un en-tête.",
        "en": "Line break not allowed in a header.",
    },
    "mail_rules_err_bad_json": {
        "fr": "Fichier de règles illisible :",
        "en": "Unreadable rules file:",
    },
    "mail_rules_err_future_version": {
        "fr": "Fichier de règles d'une version plus récente :",
        "en": "Rules file from a newer version:",
    },
    "mail_rules_err_invalid": {
        "fr": "Règle invalide :",
        "en": "Invalid rule:",
    },
    "mail_rules_err_field": {"fr": "champ inconnu", "en": "unknown field"},
    "mail_rules_err_op": {
        "fr": "opération inconnue",
        "en": "unknown operation",
    },
    "mail_rules_err_mode": {
        "fr": "mode de comparaison inconnu",
        "en": "unknown match mode",
    },
    "mail_rules_err_glob_field": {
        "fr": "le motif ne s'applique qu'à De et À/Cc",
        "en": "the pattern applies only to From and To/Cc",
    },
    "mail_rules_err_empty_value": {"fr": "valeur vide", "en": "empty value"},
    "mail_rules_err_value_too_long": {
        "fr": "valeur trop longue",
        "en": "value too long",
    },
    "mail_rules_err_regex": {
        "fr": "expression régulière invalide :",
        "en": "invalid regular expression:",
    },
    "mail_rules_err_regex_timeout": {
        "fr": "expression régulière trop lente sur ce message",
        "en": "regular expression too slow on this message",
    },
    "mail_rules_err_not_one_child": {
        "fr": "un groupe NON contient exactement une condition",
        "en": "a NOT group holds exactly one condition",
    },
    "mail_rules_err_too_deep": {
        "fr": "filtre trop profond ou trop grand",
        "en": "filter too deep or too large",
    },
    "mail_rules_err_minutes": {
        "fr": "minutes : entier de 1 à 525600",
        "en": "minutes: integer from 1 to 525600",
    },
    "mail_rules_err_max_age": {
        "fr": "âge maximal : entier de 1 à 720 heures",
        "en": "maximum age: integer from 1 to 720 hours",
    },
    "mail_rules_err_hold_first": {
        "fr": "envois retenus : entier de 1 à 10",
        "en": "held sends: integer from 1 to 10",
    },
    "mail_rules_err_kind": {
        "fr": "type d'action inconnu",
        "en": "unknown action type",
    },
    "mail_rules_err_format": {"fr": "format inconnu", "en": "unknown format"},
    "mail_rules_err_image_type": {
        "fr": "type d'image refusé :",
        "en": "image type refused:",
    },
    "mail_rules_err_image_size": {
        "fr": "image trop lourde :",
        "en": "image too large:",
    },
    "mail_rules_err_image_missing": {
        "fr": "image introuvable :",
        "en": "image not found:",
    },
    "mail_rules_err_image_pixels": {
        "fr": "image aux dimensions trop grandes :",
        "en": "image dimensions too large:",
    },
    "mail_rules_err_svg_no_converter": {
        "fr": (
            "image SVG : aucun convertisseur en PNG (rsvg-convert, cairosvg,"
            " inkscape ou ImageMagick) ; pour en installer un :"
        ),
        "en": (
            "SVG image: no PNG converter (rsvg-convert, cairosvg, inkscape"
            " or ImageMagick); to install one:"
        ),
    },
    "mail_rules_err_svg_invalid": {
        "fr": "fichier qui n'est pas une image SVG :",
        "en": "file is not an SVG image:",
    },
    "mail_rules_err_svg_external": {
        "fr": "image SVG qui renvoie à un fichier ou une ressource externe :",
        "en": "SVG image refers to an external file or resource:",
    },
    "mail_rules_err_svg_failed": {
        "fr": "conversion du SVG en PNG échouée :",
        "en": "SVG to PNG conversion failed:",
    },
    "mail_rules_err_svg_unsafe": {
        "fr": (
            "image SVG qui porte un script, un gestionnaire d'événement, une"
            " animation, un document imbriqué, une déclaration de DTD ou un"
            " codage autre qu'UTF-8 :"
        ),
        "en": (
            "SVG image carries a script, an event handler, an animation, an"
            " embedded document, a DTD declaration or an encoding other than"
            " UTF-8:"
        ),
    },
    "mail_rules_err_svg_embedded": {
        "fr": "image SVG qui intègre une autre image ou un document (data:) :",
        "en": "SVG image embeds another image or a document (data:):",
    },
    "mail_rules_fwd_separator": {
        "fr": "---------- Message transféré ----------",
        "en": "---------- Forwarded message ----------",
    },
    "mail_rules_fwd_from": {"fr": "De :", "en": "From:"},
    "mail_rules_fwd_date": {"fr": "Date :", "en": "Date:"},
    "mail_rules_fwd_to": {"fr": "À :", "en": "To:"},
    "mail_rules_fwd_cc": {"fr": "Cc :", "en": "Cc:"},
    "mail_rules_fwd_subject": {"fr": "Sujet :", "en": "Subject:"},
    "mail_rules_err_fwd_address": {
        "fr": "adresse de destination invalide :",
        "en": "invalid destination address:",
    },
    "mail_rules_err_fwd_unreadable": {
        "fr": "Message d'origine illisible : impossible de le transférer.",
        "en": "Original message unreadable: it cannot be forwarded.",
    },
    "mail_rules_reason_own_message": {
        "fr": "notre propre envoi automatique, ou une réponse à l'un d'eux",
        "en": "our own automatic message, or a reply to one",
    },
    "mail_rules_reason_resent_loop": {
        "fr": "déjà redirigé par ce compte",
        "en": "already redirected by this account",
    },
    "mail_rules_reason_delivery_report": {
        "fr": "rapport de remise ou de non-remise",
        "en": "delivery or non-delivery report",
    },
    "mail_rules_reason_auto_reply": {
        "fr": "réponse automatique (absence, accusé de réception)",
        "en": "automatic reply (out of office, acknowledgement)",
    },
    "mail_rules_reason_too_big": {
        "fr": "message trop gros pour être transféré",
        "en": "message too large to forward",
    },
    "mail_rules_reason_no_forward_target": {
        "fr": "aucune destination restante",
        "en": "no destination left",
    },
    "mail_rules_err_fwd_mode": {
        "fr": "mode de redirection inconnu :",
        "en": "unknown forward mode:",
    },
    "mail_rules_err_fwd_no_target": {
        "fr": "au moins une adresse de destination est requise",
        "en": "at least one destination address is required",
    },
    "mail_rules_err_fwd_too_many": {
        "fr": "trop d'adresses de destination ; maximum :",
        "en": "too many destination addresses; maximum:",
    },
    "mail_rules_err_fwd_intro_too_long": {
        "fr": "texte d'introduction trop long ; maximum :",
        "en": "introduction text too long; maximum:",
    },
    "mail_rules_err_fwd_images": {
        "fr": "une redirection ne porte pas d'images",
        "en": "a forward carries no images",
    },
    "mail_rules_err_fwd_self": {
        "fr": "c'est l'adresse de ce compte :",
        "en": "this is this account's address:",
    },
    "mail_rules_err_fwd_other_account": {
        "fr": "c'est l'adresse d'un autre compte configuré :",
        "en": "this is the address of another configured account:",
    },
    "mail_rules_err_fwd_duplicate": {
        "fr": "adresse déjà dans la liste :",
        "en": "address already in the list:",
    },
    "mail_rules_reason_too_old": {"fr": "trop vieux", "en": "too old"},
    "mail_rules_reason_bad_date": {
        "fr": "date de réception dans le futur",
        "en": "receive date in the future",
    },
    "mail_rules_reason_auto_submitted": {
        "fr": "message automatique",
        "en": "automatic message",
    },
    "mail_rules_reason_precedence": {
        "fr": "envoi de masse",
        "en": "bulk mail",
    },
    "mail_rules_reason_list": {
        "fr": "liste de diffusion",
        "en": "mailing list",
    },
    "mail_rules_reason_auto_response_suppress": {
        "fr": "réponses automatiques refusées par l'expéditeur",
        "en": "automatic replies refused by the sender",
    },
    "mail_rules_reason_x_loop": {
        "fr": "boucle détectée",
        "en": "loop detected",
    },
    "mail_rules_reason_spam": {"fr": "pourriel", "en": "spam"},
    "mail_rules_reason_null_sender": {
        "fr": "expéditeur vide",
        "en": "null sender",
    },
    "mail_rules_reason_no_target": {
        "fr": "aucune adresse de réponse",
        "en": "no reply address",
    },
    "mail_rules_reason_robot_sender": {
        "fr": "expéditeur automate",
        "en": "robot sender",
    },
    "mail_rules_reason_self": {
        "fr": "envoyé par ce compte",
        "en": "sent by this account",
    },
    "mail_rules_reason_other_account": {
        "fr": "autre compte configuré",
        "en": "another configured account",
    },
    "mail_rules_reason_not_addressed": {
        "fr": "non adressé à ce compte",
        "en": "not addressed to this account",
    },
    "mail_rules_reason_auth_fail": {
        "fr": "authentification en échec",
        "en": "authentication failed",
    },
    "mail_rules_reason_unauthenticated": {
        "fr": "expéditeur non authentifié",
        "en": "sender not authenticated",
    },
    "mail_rules_reason_throttled": {"fr": "limité", "en": "throttled"},
    "mail_rules_reason_pass_cap": {
        "fr": "plafond de la passe atteint",
        "en": "pass cap reached",
    },
    "mail_rules_reason_hour_cap": {
        "fr": "plafond horaire atteint",
        "en": "hourly cap reached",
    },
    "mail_rules_reason_hold_first": {
        "fr": "premier envoi à approuver",
        "en": "first send awaiting approval",
    },
    "mail_rules_reason_cache_rebuilt": {
        "fr": "cache recréé",
        "en": "cache rebuilt",
    },
    "mail_rules_reason_offline": {"fr": "hors ligne", "en": "offline"},
    "mail_rules_reason_smtp_transient": {
        "fr": "refus temporaire du serveur",
        "en": "temporary server refusal",
    },
    "mail_rules_reason_smtp_permanent": {
        "fr": "refus définitif du serveur",
        "en": "permanent server refusal",
    },
    "mail_rules_reason_rule_disabled": {
        "fr": "règle désactivée",
        "en": "rule disabled",
    },
    "mail_rules_reason_rule_changed": {
        "fr": "règle modifiée depuis",
        "en": "rule changed since",
    },
    "mail_rules_reason_expired": {"fr": "expiré", "en": "expired"},
    "mail_rules_reason_attempts_exhausted": {
        "fr": "essais épuisés",
        "en": "attempts exhausted",
    },
    "mail_rules_reason_rcpt_retry": {
        "fr": "destinataires refusés, nouvel essai en file",
        "en": "recipients refused, retry queued",
    },
    "mail_rules_reason_rcpt_refused": {
        "fr": "destinataires refusés pour de bon",
        "en": "recipients refused for good",
    },
    "mail_rules_reason_rcpt_retried": {
        "fr": "remis à tous après un nouvel essai",
        "en": "delivered to all after a retry",
    },
    "mail_rules_reason_claimed_elsewhere": {
        "fr": "déjà revendiqué ($ErpLibreRule posé), quelle que soit la règle",
        "en": "already claimed ($ErpLibreRule set), whatever the rule",
    },
    "mail_rules_reason_claim_uncertain": {
        "fr": "revendication incertaine après une interruption, laissé sans envoi : vérifiez Envoyés, puis libérez-le à la main si besoin",
        "en": "claim uncertain after an interruption, left unsent: check Sent, then release it by hand if needed",
    },
    "mail_rules_reason_claim_gone": {
        "fr": "message disparu du serveur avant sa revendication",
        "en": "message gone from the server before it could be claimed",
    },
    "mail_rules_reason_ready": {
        "fr": "prêt à partir",
        "en": "ready to leave",
    },
    "mail_rules_reason_ready_released": {
        "fr": "libéré à la main, prêt à partir",
        "en": "released by hand, ready to leave",
    },
    "mail_rules_reason_sending": {
        "fr": "envoi en cours",
        "en": "sending",
    },
    "mail_rules_reason_send_uncertain": {
        "fr": "envoi interrompu, issue inconnue, non renvoyé : vérifiez Envoyés, répondez à la main si besoin",
        "en": "send interrupted, outcome unknown, not sent again: check Sent, reply by hand if needed",
    },
    "mail_rules_reason_claim_failed": {
        "fr": "revendication impossible après plusieurs passes, laissé sans envoi : libérable à la main",
        "en": "claim failed over several passes, left unsent: can be released by hand",
    },
    "mail_rules_reason_released": {
        "fr": "libéré à la main, réévalué à la prochaine passe en ligne",
        "en": "released by hand, evaluated again at the next online pass",
    },
    "mail_rules_reason_release_unmatched": {
        "fr": "libéré à la main ; à la réévaluation, la règle n'a rien décidé pour ce message (désactivée, réarmée, filtre changé, ou arrêtée par une règle précédente)",
        "en": "released by hand; when evaluated again, the rule decided nothing for this message (disabled, re-armed, filter changed, or stopped by an earlier rule)",
    },
    "mail_rules_reason_media": {
        "fr": "image illisible",
        "en": "unreadable image",
    },
    "mail_rules_reason_build_error": {
        "fr": "message impossible à construire",
        "en": "message could not be built",
    },
    "mail_rules_reason_regex_timeout": {
        "fr": "expression régulière trop lente",
        "en": "regular expression too slow",
    },
    "mail_rules_reason_stats_cap": {
        "fr": "plafond quotidien du rapport atteint",
        "en": "daily report cap reached",
    },
    "mail_rules_reason_body_unavailable": {
        "fr": "corps illisible",
        "en": "unreadable body",
    },
    "mail_rules_reason_gone": {
        "fr": "disparu du serveur",
        "en": "gone from the server",
    },
    "mail_rules_reason_catchup_overflow": {
        "fr": "rattrapage dépassé",
        "en": "catch-up limit exceeded",
    },
    "mail_rules_outcome_pending": {"fr": "en cours", "en": "pending"},
    "mail_rules_outcome_sent": {"fr": "envoyé", "en": "sent"},
    "mail_rules_outcome_queued": {"fr": "en file", "en": "queued"},
    "mail_rules_outcome_held": {"fr": "retenu", "en": "held"},
    "mail_rules_outcome_skipped": {"fr": "ignoré", "en": "skipped"},
    "mail_rules_outcome_failed": {"fr": "échec", "en": "failed"},
    "mail_rules_outcome_expired": {"fr": "expiré", "en": "expired"},
    "mail_rules_outcome_partial": {"fr": "partiel", "en": "partial"},
    "mail_rules_err_template_var": {
        "fr": "variable inconnue dans le gabarit :",
        "en": "unknown template variable:",
    },
    "mail_rules_err_template_block_subject": {
        "fr": "un bloc de rapport ne va pas dans le sujet :",
        "en": "a report block cannot go in the subject:",
    },
    "mail_rules_err_template_block_tag": {
        "fr": "un bloc de rapport ne va pas dans une balise HTML :",
        "en": "a report block cannot go inside an HTML tag:",
    },
    "mail_rules_err_template_reply_var": {
        "fr": "variable de rapport dans une réponse personnalisée :",
        "en": "report variable in a custom reply:",
    },
    "mail_stats_default_body": {
        "fr": (
            "Bonjour,\n\nMerci pour votre message. Voici l'activité récente"
            " de cette boîte de courriel.\n\n{{rapport}}\n"
        ),
        "en": (
            "Hello,\n\nThank you for your message. Here is the recent"
            " activity of this mailbox.\n\n{{rapport}}\n"
        ),
    },
    "mail_stats_report_days_title": {
        "fr": "Activité des {n} derniers jours",
        "en": "Activity over the last {n} days",
    },
    "mail_stats_report_weeks_title": {
        "fr": "Par semaine ISO ({n} dernières)",
        "en": "By ISO week (last {n})",
    },
    "mail_stats_report_col_day": {"fr": "Jour", "en": "Day"},
    "mail_stats_report_col_week": {"fr": "Semaine", "en": "Week"},
    "mail_stats_report_col_week_start": {"fr": "Du", "en": "From"},
    "mail_stats_report_col_received": {"fr": "Reçus", "en": "Received"},
    "mail_stats_report_col_seen": {"fr": "Lus", "en": "Read"},
    "mail_stats_report_col_answered": {"fr": "Répondus", "en": "Answered"},
    "mail_stats_report_total": {"fr": "Total", "en": "Total"},
    "mail_stats_report_mailbox_delay": {
        "fr": "Délai moyen de réponse de la boîte ({n} derniers jours) :",
        "en": "Mailbox average reply delay (last {n} days):",
    },
    "mail_stats_report_mailbox_none": {
        "fr": "Aucune réponse enregistrée sur les {n} derniers jours.",
        "en": "No reply recorded over the last {n} days.",
    },
    "mail_stats_report_mailbox_few": {
        "fr": (
            "Trop peu de réponses sur les {n} derniers jours pour une moyenne."
        ),
        "en": "Too few replies over the last {n} days for an average.",
    },
    "mail_stats_report_requester_delay": {
        "fr": "Votre délai moyen de réponse ({n} derniers jours) :",
        "en": "Your average reply delay (last {n} days):",
    },
    "mail_stats_report_based_on": {
        "fr": "(sur {n} délais connus)",
        "en": "(over {n} known delays)",
    },
    "mail_stats_report_requester_none": {
        "fr": (
            "Aucun de vos messages des {n} derniers jours n'a encore reçu"
            " de réponse."
        ),
        "en": (
            "None of your messages from the last {n} days has been"
            " answered yet."
        ),
    },
    "mail_stats_report_generated": {"fr": "Rapport du", "en": "Report of"},
    "mail_stats_report_local_time": {
        "fr": "Jours et semaines en heure locale ({tz}).",
        "en": "Days and weeks in local time ({tz}).",
    },
    "mail_stats_report_unit_day": {"fr": "j", "en": "d"},
    "mail_stats_var_rapport": {
        "fr": "rapport complet : tableaux, délais, date",
        "en": "full report: tables, delays, date",
    },
    "mail_stats_var_rapport_jours": {
        "fr": "tableau par jour, avec son titre",
        "en": "daily table, with its title",
    },
    "mail_stats_var_rapport_semaines": {
        "fr": "tableau par semaine ISO, avec son titre",
        "en": "ISO weekly table, with its title",
    },
    "mail_stats_var_recus_total": {
        "fr": "messages reçus sur la période",
        "en": "messages received over the period",
    },
    "mail_stats_var_lus_total": {
        "fr": "messages lus parmi les reçus",
        "en": "read messages among those received",
    },
    "mail_stats_var_repondus_total": {
        "fr": "messages répondus parmi les reçus",
        "en": "answered messages among those received",
    },
    "mail_stats_var_delai_moyen": {
        "fr": "délai moyen de réponse aux messages du demandeur",
        "en": "average reply delay to the requester's messages",
    },
    "mail_stats_var_delai_moyen_boite": {
        "fr": "délai moyen de réponse de la boîte",
        "en": "mailbox average reply delay",
    },
    "mail_stats_var_demandeur_recus": {
        "fr": "messages du demandeur reçus dans la fenêtre",
        "en": "requester's messages received in the window",
    },
    "mail_stats_var_demandeur_repondus": {
        "fr": "messages du demandeur qui ont reçu une réponse",
        "en": "requester's messages that were answered",
    },
    "mail_stats_var_jours": {
        "fr": "nombre de jours du tableau",
        "en": "number of days in the table",
    },
    "mail_stats_var_semaines": {
        "fr": "nombre de semaines du tableau",
        "en": "number of weeks in the table",
    },
    "mail_stats_var_fenetre_jours": {
        "fr": "fenêtre des délais, en jours",
        "en": "delay window, in days",
    },
    "mail_stats_var_periode_debut": {
        "fr": "premier jour de la période",
        "en": "first day of the period",
    },
    "mail_stats_var_periode_fin": {
        "fr": "dernier jour de la période (hier)",
        "en": "last day of the period (yesterday)",
    },
    "mail_stats_var_date_rapport": {
        "fr": "date et heure du rapport",
        "en": "report date and time",
    },
    "mail_rules_reason_not_armed": {
        "fr": "règle pas encore armée pour ce message",
        "en": "rule not yet armed for this message",
    },
    "mail_rules_reason_duplicate": {
        "fr": "message déjà traité par la règle",
        "en": "message already handled by the rule",
    },
    "mail_rules_reason_no_match": {
        "fr": "ne correspond pas au filtre",
        "en": "does not match the filter",
    },
}
