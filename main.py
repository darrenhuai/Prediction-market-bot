from __future__ import annotations
import sys
from pathlib import Path
from src.common.analysis import Analysis
from src.common.indexer import Indexer

def _title(s):
    return s.replace('_', ' ').title()

def _pick(options, title):
    print(f'\n{title}')
    print('-' * 50)
    for i, opt in enumerate(options):
        print(f'  {i + 1}. {opt}')
    print('-' * 50)
    try:
        raw = input('Enter number: ').strip()
        choice = int(raw) - 1
        if 0 <= choice < len(options):
            return choice
        return None
    except (ValueError, KeyboardInterrupt):
        return None

def index(name=None):
    indexers = Indexer.load()
    if name:
        for cls in indexers:
            inst = cls()
            if inst.name == name:
                inst.run()
                return
    options = [f'{_title(cls().name)}: {cls().description}' for cls in indexers] + ['[Exit]']
    choice = _pick(options, 'Select an indexer:')
    if choice is None or choice == len(options) - 1:
        return
    inst = indexers[choice]()
    print(f'\nRunning: {inst.name}\n')
    inst.run()

def analyze(name=None):
    analyses = Analysis.load()
    output_dir = Path('output')
    if name:
        for cls in analyses:
            inst = cls()
            if inst.name == name:
                inst.save(output_dir, formats=['json','csv'])
                return
    options = ['[All] Run all analyses'] + [f'{_title(cls().name)}: {cls().description}' for cls in analyses] + ['[Exit]']
    choice = _pick(options, 'Select an analysis:')
    if choice is None or choice == len(options) - 1:
        return
    if choice == 0:
        for cls in analyses:
            cls().save(output_dir, formats=['json','csv'])
    else:
        analyses[choice - 1]().save(output_dir, formats=['json','csv'])

def main():
    if len(sys.argv) < 2:
        print('Usage: uv run main.py <analyze|index> [name]')
        sys.exit(0)
    cmd = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == 'analyze':
        analyze(name)
    elif cmd == 'index':
        index(name)
    else:
        print(f'Unknown command: {cmd}')

if __name__ == '__main__':
    main()
