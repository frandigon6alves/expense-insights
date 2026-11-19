#!/usr/bin/env sh
# Re-extract translatable strings, merge them into every catalogue and compile
# the .mo files. Run from the repository root after changing any user-facing text,
# then fill in the new/empty msgstr entries in each .po file and run it again.
set -eu

LOCALES=src/expense_insights/locales
DOMAIN=expense_insights

pybabel -q extract -F babel.cfg -o "$LOCALES/$DOMAIN.pot" \
    --project=expense-insights --copyright-holder="Franciellen Gonçalves" \
    --msgid-bugs-address="https://github.com/frandigon6alves/expense-insights/issues" \
    --no-location --sort-output src
pybabel -q update -D "$DOMAIN" -i "$LOCALES/$DOMAIN.pot" -d "$LOCALES" \
    --no-fuzzy-matching --ignore-obsolete
pybabel compile -D "$DOMAIN" -d "$LOCALES" --statistics
