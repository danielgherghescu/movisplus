#!/usr/bin/env python3
"""
Extract questionnaire data from all 8 Script HTML files into a single CSV.
"""

import re
import csv
import os
from html.parser import HTMLParser
from html import unescape

BASE = os.path.dirname(os.path.abspath(__file__))

SCRIPTS = [
    ("SOLD",              "Sold/Script_Sold.html"),
    ("UMAR",              "Umar/Script_Umar.html"),
    ("COT",               "Cot/Script_Cot.html"),
    ("GENUNCHI",          "Genunchi/Script_Genunchi.html"),
    ("GLEZNA SI PICIOR",  "Glezna_si_Picior/Script_Glezna_si_Picior.html"),
    ("PUMN SI MANA",      "Pumn_si_Mana/Script_Pumn_si_Mana.html"),
    ("COLOANA CERVICALA",  "Coloana_Cervicala/Script_Coloana_Cervicala.html"),
    ("COLOANA LOMBARA",    "Coloana_Lombara/Script_Coloana_Lombara.html"),
]


# ─── HTML PARSING ────────────────────────────────────────────────────────────

class QuestionExtractor(HTMLParser):
    """
    Extract per-card data. For each card, track:
    - key_to_question: maps each option key to the most recently seen question text
    - key_to_options: maps each option key to its list of option labels
    """

    def __init__(self):
        super().__init__()
        # card_id -> { 'key_to_question': {key: text}, 'key_to_options': {key: [labels]} }
        self.cards = {}
        self._current_card_id = None
        self._card_depth = 0
        self._depth = 0

        # Track the last question text seen within a card
        self._last_question_text = None

        # Capture state
        self._capture = None  # 'question-text', 'test-question', 'sub-question', 'option-label', 'color-option-label'
        self._text_buf = ''

        # Option tracking
        self._in_option = False
        self._option_input_name = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        self._depth += 1

        cls = attrs_dict.get('class', '')
        card_id = attrs_dict.get('id', '')

        # Detect card boundaries
        if tag == 'div' and card_id.startswith('card-'):
            if 'question-card' in cls or 'test-card' in cls:
                self._current_card_id = card_id
                self._card_depth = self._depth
                self._last_question_text = None
                if card_id not in self.cards:
                    self.cards[card_id] = {'key_to_question': {}, 'key_to_options': {}}

        if self._current_card_id is None:
            return

        # Capture question texts (all types)
        if tag == 'div' and 'question-text' in cls:
            self._capture = 'question-text'
            self._text_buf = ''
        elif tag == 'div' and 'test-question' in cls:
            self._capture = 'test-question'
            self._text_buf = ''
        elif tag == 'div' and 'sub-question' in cls:
            self._capture = 'sub-question'
            self._text_buf = ''

        # Track option/color-option labels
        if tag == 'label' and ('option' in cls.split() or 'color-option' in cls.split()):
            self._in_option = True
            self._option_input_name = None
            onclick = attrs_dict.get('onclick', '')
            m = re.search(r"'([a-z]\d+[a-z]?(?:-none)?)'", onclick)
            if m:
                self._option_input_name = m.group(1)

        if tag == 'input' and self._in_option:
            name = attrs_dict.get('name', '')
            if name:
                self._option_input_name = name

        if tag == 'span' and 'option-label' in cls:
            self._capture = 'option-label'
            self._text_buf = ''
        elif tag == 'span' and 'color-option-label' in cls:
            self._capture = 'color-option-label'
            self._text_buf = ''

    def handle_endtag(self, tag):
        # Question text captured - update last_question_text
        if self._capture in ('question-text', 'test-question', 'sub-question') and tag == 'div':
            text = self._clean(self._text_buf)
            if text:
                self._last_question_text = text
            self._capture = None
            self._text_buf = ''

        # Option label captured - associate with key and last question
        if self._capture in ('option-label', 'color-option-label') and tag == 'span':
            text = self._clean(self._text_buf)
            if text and self._current_card_id and self._option_input_name:
                key = self._option_input_name
                card = self.cards[self._current_card_id]

                # Record question text for this key (first occurrence wins)
                if key not in card['key_to_question'] and self._last_question_text:
                    card['key_to_question'][key] = self._last_question_text

                # Record option label
                if key not in card['key_to_options']:
                    card['key_to_options'][key] = []
                card['key_to_options'][key].append(text)
            self._capture = None
            self._text_buf = ''

        if tag == 'label':
            self._in_option = False

        # Close card
        if self._current_card_id and tag == 'div' and self._depth == self._card_depth:
            self._current_card_id = None
            self._last_question_text = None

        self._depth -= 1

    def handle_data(self, data):
        if self._capture:
            self._text_buf += data

    def handle_entityref(self, name):
        if self._capture:
            self._text_buf += unescape(f'&{name};')

    def handle_charref(self, name):
        if self._capture:
            self._text_buf += unescape(f'&#{name};')

    def _clean(self, text):
        text = re.sub(r'\s+', ' ', text).strip()
        return text


# ─── JS CONSTANT EXTRACTION ──────────────────────────────────────────────────

def extract_js_block(html, var_name):
    """Extract a JS const block (array or object) from HTML."""
    pattern = rf'const\s+{re.escape(var_name)}\s*=\s*'
    m = re.search(pattern, html)
    if not m:
        return None
    start = m.end()

    open_char = html[start]
    if open_char == '[':
        close_char = ']'
    elif open_char == '{':
        close_char = '}'
    else:
        return None

    depth = 0
    i = start
    while i < len(html):
        c = html[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return html[start:i+1]
        elif c in ('"', "'", '`'):
            quote = c
            i += 1
            while i < len(html) and html[i] != quote:
                if html[i] == '\\':
                    i += 1
                i += 1
        i += 1
    return None


def parse_q_array(js_text):
    """Parse [{ key: 'a1', label: '...' }, ...] or [{ key: 't1', clinName: '...' }, ...]"""
    items = []
    for m in re.finditer(r'\{([^}]+)\}', js_text):
        obj_text = m.group(1)
        key_m = re.search(r"key\s*:\s*'([^']+)'", obj_text)
        label_m = re.search(r"label\s*:\s*'([^']+)'", obj_text)
        clin_m = re.search(r"clinName\s*:\s*'([^']+)'", obj_text)
        multi_m = re.search(r"multi\s*:\s*true", obj_text)
        none_m = re.search(r"noneName\s*:\s*'([^']+)'", obj_text)

        if key_m:
            item = {'key': key_m.group(1)}
            if label_m:
                item['label'] = label_m.group(1)
            if clin_m:
                item['clinName'] = clin_m.group(1)
            if multi_m:
                item['multi'] = True
            if none_m:
                item['noneName'] = none_m.group(1)
            items.append(item)
    return items


def parse_r_object(js_text):
    """Parse { a1: { 'key': 'value', ... }, a2: { ... }, ... }"""
    result = {}
    js_text = js_text.strip()
    if js_text.startswith('{'):
        js_text = js_text[1:]
    if js_text.endswith('}'):
        js_text = js_text[:-1]

    pos = 0
    while pos < len(js_text):
        key_m = re.search(r'(\w+)\s*:\s*\{', js_text[pos:])
        if not key_m:
            break
        key = key_m.group(1)
        brace_start = pos + key_m.end() - 1

        depth = 0
        i = brace_start
        while i < len(js_text):
            if js_text[i] == '{':
                depth += 1
            elif js_text[i] == '}':
                depth -= 1
                if depth == 0:
                    block = js_text[brace_start:i+1]
                    result[key] = parse_inner_object(block)
                    pos = i + 1
                    break
            elif js_text[i] in ("'", '"'):
                quote = js_text[i]
                i += 1
                while i < len(js_text) and js_text[i] != quote:
                    if js_text[i] == '\\':
                        i += 1
                    i += 1
            i += 1
        else:
            break
    return result


def parse_inner_object(block):
    """Parse { 'key1': 'value1', 'key2': 'value2', ... }"""
    result = {}
    pairs = re.findall(
        r"""(?:'([^']*)'|"([^"]*)"|(\w+))\s*:\s*(?:'([^']*)'|"([^"]*)")""",
        block
    )
    for p in pairs:
        key = p[0] or p[1] or p[2]
        value = p[3] or p[4]
        if key:
            result[key] = value
    return result


# ─── LOOKUP HELPERS ──────────────────────────────────────────────────────────

def get_question_text_for_key(cards, key):
    """Get the question text for a given key."""
    # Direct card lookup (e.g. card-q1, card-a1, card-t1)
    card_id = f"card-{key}"
    if card_id in cards:
        card = cards[card_id]
        if key in card['key_to_question']:
            return card['key_to_question'][key]

    # For subquestion keys (t1a, t9b, etc.), look in parent card
    base_m = re.match(r'^(t\d+)([a-z])$', key)
    if base_m:
        base_key = base_m.group(1)
        card_id = f"card-{base_key}"
        if card_id in cards:
            card = cards[card_id]
            if key in card['key_to_question']:
                return card['key_to_question'][key]

    return ''


def get_options_for_key(cards, key):
    """Get option labels for a given key."""
    # Direct card lookup
    card_id = f"card-{key}"
    if card_id in cards:
        card = cards[card_id]
        all_opts = list(card['key_to_options'].get(key, []))
        none_key = f"{key}-none"
        if none_key in card['key_to_options']:
            all_opts.extend(card['key_to_options'][none_key])
        if all_opts:
            return all_opts

    # For subquestion keys (t1a, t9b, etc.), look in parent card
    base_m = re.match(r'^(t\d+)([a-z])$', key)
    if base_m:
        base_key = base_m.group(1)
        card_id = f"card-{base_key}"
        if card_id in cards:
            card = cards[card_id]
            all_opts = list(card['key_to_options'].get(key, []))
            none_key = f"{key}-none"
            if none_key in card['key_to_options']:
                all_opts.extend(card['key_to_options'][none_key])
            if all_opts:
                return all_opts

    return []


# ─── CSV GENERATION ──────────────────────────────────────────────────────────

def main():
    rows = []

    # Use the first file (Sold) for Anamneza, since they're identical across files
    first_file = os.path.join(BASE, SCRIPTS[0][1])
    with open(first_file, 'r', encoding='utf-8') as f:
        first_html = f.read()

    parser = QuestionExtractor()
    parser.feed(first_html)
    first_cards = parser.cards

    anamneza_q_js = extract_js_block(first_html, 'Anamneza_Q')
    anamneza_r_js = extract_js_block(first_html, 'Anamneza_R')
    anamneza_q = parse_q_array(anamneza_q_js) if anamneza_q_js else []
    anamneza_r = parse_r_object(anamneza_r_js) if anamneza_r_js else {}

    # ─── SECTION 1: ANAMNEZA GENERALA ─────────────────────────
    rows.append(['', '', '', ''])
    rows.append(['--- ANAMNEZA GENERALA ---', '', '', ''])

    for q_item in anamneza_q:
        key = q_item['key']
        label = q_item.get('label', '')
        q_text = get_question_text_for_key(first_cards, key)
        opts = get_options_for_key(first_cards, key)
        opts_text = ' | '.join(opts) if opts else ''
        r_map = anamneza_r.get(key, {})
        clin_r_text = ' | '.join(r_map.values()) if r_map else ''
        rows.append([q_text, opts_text, label, clin_r_text])

    # ─── SECTION 2: PER-SCRIPT SPECIFICS ──────────────────────
    for script_name, script_path in SCRIPTS:
        filepath = os.path.join(BASE, script_path)
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()

        parser = QuestionExtractor()
        parser.feed(html)
        cards = parser.cards

        intrebari_q_js = extract_js_block(html, 'Intrebari_Q')
        intrebari_r_js = extract_js_block(html, 'Intrebari_R')
        teste_q_js = extract_js_block(html, 'Teste_Q')
        teste_r_js = extract_js_block(html, 'Teste_R')

        intrebari_q = parse_q_array(intrebari_q_js) if intrebari_q_js else []
        intrebari_r = parse_r_object(intrebari_r_js) if intrebari_r_js else {}
        teste_q = parse_q_array(teste_q_js) if teste_q_js else []
        teste_r = parse_r_object(teste_r_js) if teste_r_js else {}

        rows.append(['', '', '', ''])
        rows.append([f'--- {script_name} ---', '', '', ''])

        # ─── INTREBARI SPECIFICE ──────────────
        rows.append(['-- INTREBARI SPECIFICE --', '', '', ''])
        for q_item in intrebari_q:
            key = q_item['key']
            label = q_item.get('label', '')
            q_text = get_question_text_for_key(cards, key)
            opts = get_options_for_key(cards, key)
            opts_text = ' | '.join(opts) if opts else ''
            r_map = intrebari_r.get(key, {})
            clin_r_text = ' | '.join(r_map.values()) if r_map else ''
            rows.append([q_text, opts_text, label, clin_r_text])

        # ─── TESTE SPECIFICE ──────────────────
        rows.append(['-- TESTE SPECIFICE --', '', '', ''])
        for t_item in teste_q:
            key = t_item['key']
            clin_name = t_item.get('clinName', '')
            q_text = get_question_text_for_key(cards, key)
            opts = get_options_for_key(cards, key)
            opts_text = ' | '.join(opts) if opts else ''
            r_map = teste_r.get(key, {})
            clin_r_text = ' | '.join(r_map.values()) if r_map else ''
            rows.append([q_text, opts_text, clin_name, clin_r_text])

    # ─── WRITE CSV ────────────────────────────────────────────
    output_path = os.path.join(BASE, 'questionnaire_export.csv')
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(['Intrebare pacient', 'Raspunsuri pacient', 'Intrebare clinica', 'Raspuns clinic'])
        for row in rows:
            writer.writerow(row)

    print(f"CSV written to {output_path}")
    print(f"Total rows (excluding header): {len(rows)}")


if __name__ == '__main__':
    main()
