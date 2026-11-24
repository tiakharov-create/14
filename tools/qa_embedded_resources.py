#!/usr/bin/env python3
"""Repair machine-translated embedded-data labels using a curated cultivation glossary."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

WORDS = {
    "jade": "нефритовый", "heaven": "небесный", "heavenly": "небесный", "body": "тело", "ink": "чернила",
    "paper": "бумага", "wood": "древесина", "spirit": "духовный", "core": "ядро", "beast": "звериный",
    "thunder": "громовой", "chaos": "хаос", "primordial": "первозданный", "iron": "железный", "frost": "морозный",
    "immortal": "бессмертный", "ancient": "древний", "year": "летний", "cloud": "облачный", "star": "звёздный",
    "pure": "чистый", "flame": "пламя", "tide": "приливный", "verdant": "изумрудный", "thousand": "тысячный",
    "born": "рождённый", "grass": "трава", "mountain": "горный", "gold": "золотой", "deep": "глубинный",
    "profound": "сокровенный", "hundred": "сотенный", "rime": "инеевый", "plain": "равнинный", "grade": "ранг",
    "root": "корень", "lotus": "лотос", "loess": "лёссовый", "gale": "штормовой", "soul": "душа", "blood": "кровавый",
    "silk": "шёлк", "heart": "сердце", "ginseng": "женьшень", "bamboo": "бамбуковый", "dragon": "дракон", "steel": "стальной",
    "earth": "земля", "fallen": "падший", "nine": "девять", "water": "вода", "wind": "ветер", "harmony": "гармония",
    "common": "обычный", "rough": "грубый", "steeped": "насыщенный", "woven": "сплетённый", "golden": "золотой",
    "blade": "клинок", "feather": "перо", "storm": "буря", "ghost": "призрачный", "demon": "демон", "silver": "серебряный",
    "sap": "сок", "refined": "очищенный", "cinder": "угольный", "cypress": "кипарис", "hemp": "пеньковый", "fine": "тонкий",
    "phoenix": "феникс", "ember": "уголь", "bronze": "бронзовый", "vein": "жила", "dust": "пыль", "green": "зелёный",
    "riverweed": "речная водоросль", "oak": "дуб", "edge": "острие", "venom": "яд", "abyssal": "бездна", "stone": "камень",
    "flower": "цветок", "copper": "медь", "wild": "дикий", "moss": "мох", "snow": "снег", "raw": "сырой", "ore": "руда",
    "myriad": "мириады", "sun": "солнце", "ten": "десять", "void": "пустота", "nether": "нижний мир", "yellow": "жёлтый",
    "lesser": "малый", "purple": "фиолетовый", "defying": "бросающий вызов", "vine": "лоза", "dao": "Дао", "meridians": "меридианы",
    "shadow": "теневой", "claw": "коготь", "celestial": "небесный", "devouring": "пожирающий", "black": "чёрный", "bone": "кость",
    "fruit": "плод", "marrow": "костный мозг", "crystal": "кристалл", "moon": "луна", "devil": "дьявол", "wolf": "волк",
    "bite": "укус", "charge": "атака", "coil": "кольцо", "flood": "потоп", "tidal": "приливный", "breath": "дыхание",
    "roar": "рёв", "crow": "ворон", "fire": "огонь", "serpent": "змей", "ninefold": "девятикратный", "qilin": "цилинь",
    "kunpeng": "Куньпэн", "heavens": "небеса", "fox": "лисий", "tortoise": "черепаха", "scale": "чешуя", "ages": "веков",
    "white": "белый", "west": "запад", "killing": "смертоносный", "vermilion": "алый", "ice": "лёд", "candle": "свеча",
    "fortune": "удача", "grave": "могила", "wail": "вопль", "corpse": "труп", "armed": "вооружённый", "cold": "холодный",
    "guard": "страж", "hellfire": "адское пламя", "brimstone": "сера", "asura": "асура", "abyss": "бездна", "gathering": "собирающий",
    "calming": "успокаивающий", "mushroom": "гриб", "peach": "персик", "thunderstruck": "поражённый молнией", "array": "массив",
    "chime": "колокольчик", "orchid": "орхидея", "meteor": "метеор", "bell": "колокол", "evergreen": "вечнозелёный",
    "adamant": "несокрушимый", "tempered": "закалённый", "vessel": "сосуд", "hands": "руки", "eyes": "глаза", "boundless": "бескрайний",
    "sea": "море", "bloodfang": "кровавый клык", "backed": "спинный", "boar": "кабан", "tusk": "бивень", "python": "питон",
    "crushing": "сокрушительный", "leopard": "леопард", "ape": "обезьяна", "fist": "кулак", "spider": "паук", "freezing": "леденящий",
    "lion": "лев", "inferno": "преисподняя", "headed": "главый", "judgement": "кара", "nirvana": "нирвана", "stampede": "лавина",
    "thornback": "шипастый", "pangolin": "панголин", "rolling": "катящийся", "thorn": "шип", "crush": "сокрушение", "rhinoceros": "носорог",
    "boulder": "валун", "eagle": "орёл", "ghostfire": "призрачное пламя", "foxfire": "лисье пламя", "bewitchment": "чары",
    "bearing": "несущий", "stomp": "топот", "mirrorscale": "зеркальная чешуя", "basilisk": "василиск", "lash": "удар",
    "treant": "древесный дух", "snare": "ловушка", "colour": "цветной", "deer": "олень", "bloom": "цветение", "voidblade": "клинок пустоты",
    "mantis": "богомол", "space": "пространство", "scythe": "коса", "cicada": "цикада", "song": "песнь", "summers": "лет",
    "tiger": "тигр", "bird": "птица", "li": "ли", "frozen": "замёрзший", "sky": "небо", "taotie": "Таотэ", "maw": "пасть",
    "wyrm": "дракон", "day": "день", "night": "ночь", "cat": "кот", "beckoning": "манящий", "paw": "лапа", "hungry": "голодный",
    "ravenous": "ненасытный", "grasp": "хватка", "wandering": "бродячий", "hopping": "прыгающий", "stiff": "окоченевший",
    "strike": "удар", "drowning": "утопляющий", "embrace": "объятие", "springs": "источник", "ox": "бык", "head": "голова",
    "halberd": "алебарда", "courts": "чертоги", "horse": "лошадь", "face": "лик", "chaining": "сковывающий", "fork": "трёхзубец",
    "raven": "ворон", "omen": "знамение", "cry": "крик", "truth": "истина", "hearing": "слышащий", "diting": "Дитин",
    "hears": "слышит", "lies": "ложь", "king": "король", "imps": "бесы", "imp": "бес", "spat": "плевок", "drinking": "пьющий",
    "hound": "гончая", "warrior": "воин", "six": "шесть", "cleave": "рассекающий", "centipede": "сороконожка", "legged": "ногий",
    "whisper": "шёпот", "your": "твой", "own": "собственный", "doubt": "сомнение", "wyvern": "виверна", "rakshasa": "ракшаса",
    "man": "человек", "eating": "пожирающий", "talons": "когти", "behemoth": "чудовище", "trampling": "топчущий", "gaze": "взгляд",
    "devours": "пожирает", "qi": "ци", "snake": "змея", "foundation": "основание", "establishment": "создание", "leaf": "лист",
    "nascent": "зарождающийся", "lingzhi": "линчжи", "red": "красный", "starfall": "звездопад", "talisman": "талисман", "cinnabar": "киноварь",
    "starlight": "звёздный свет", "flag": "знамя", "thunderroot": "громовой корень", "longevity": "долголетие", "frostmarrow": "ледяной мозг",
    "willow": "ива", "parasol": "павловния", "warm": "тёплый", "nourishing": "питающий", "bloodvine": "кровавая лоза",
    "mist": "туман", "lily": "лилия", "tail": "хвост", "glacial": "ледниковый", "earthvein": "земная жила", "veil": "пелена",
    "intent": "намерение", "peachwood": "персиковая древесина", "heartwood": "ядровая древесина", "ironbark": "железная кора", "shell": "панцирь",
    "thunderwood": "громовая древесина", "phantom": "фантомный", "dew": "роса", "seed": "семя", "vitality": "жизненная сила",
    "shield": "щит", "everfrost": "вечная стужа", "fusang": "Фусан", "world": "мир", "tree": "дерево", "branch": "ветвь",
    "scroll": "свиток", "gengjin": "Гэнцзинь", "ordinary": "обычное", "robust": "крепкий", "bones": "кости", "keen": "острый",
    "sense": "чутьё", "sensitive": "чувствительный", "sickly": "болезненный", "withered": "увядающий", "spring": "весна",
    "poison": "яд", "touched": "тронутый", "innate": "врождённый", "sword": "меч", "yin": "инь", "yang": "ян", "blazing": "пылающий",
    "skin": "кожа", "grace": "благодать", "fortunate": "удачливый", "swift": "быстрый", "gifted": "одарённый", "seer": "провидец",
    "mirror": "зеркало", "lake": "озеро", "lightning": "молния", "taiji": "тайцзи", "five": "пять", "phases": "стихий",
    "bottomless": "бездонный", "dantian": "даньтянь", "vast": "обширный", "consciousness": "сознание", "undying": "неумирающий",
    "treading": "ступающий", "feet": "ступни", "crossed": "пересечённый", "retribution": "воздаяние", "karmic": "кармический",
    "sovereign": "владыка", "samsara": "сансара", "reversed": "обращённый", "tyrant": "тиран", "war": "война", "god": "бог",
    "forging": "ковка", "vajra": "ваджра", "quelling": "усмиряющий", "upholding": "поддерживающий", "sect": "секта",
    "faces": "лики", "righteous": "праведный", "broken": "сломанный", "endless": "бесконечный", "rebirth": "перерождение",
    "great": "великий", "withering": "увядание", "frail": "хрупкий", "porous": "пористый", "glass": "стекло", "burning": "пылающий",
    "life": "жизнь", "overlord": "повелитель", "cauldron": "котёл", "anvil": "наковальня", "thread": "нить", "soil": "почва",
    "reading": "чтение", "gu": "гу", "nest": "гнездо", "kin": "род",
}

PHRASES = {
    "Bloodfang Wolf": "Волк Кровавого Клыка", "Iron-Backed Boar": "Железноспинный кабан", "Jade Python": "Нефритовый питон",
    "Rending Bite": "Разрывающий укус", "Tusk Charge": "Атака клыками", "Crushing Coil": "Сокрушительное кольцо",
    "Shadow Claw": "Теневой коготь", "Thunder Fist": "Громовой кулак", "Nine-Headed Serpent": "Девятиглавый змей",
    "Ninefold Venom": "Девятикратный яд", "Ancient Qilin": "Древний цилинь", "Heavenly Judgement": "Небесная кара",
    "Nine Heavens Thunder": "Гром девяти небес", "Heavenly Phoenix": "Небесный феникс", "Chaos Qilin": "Цилинь хаоса",
    "Void-Devouring Taotie": "Пожирающий пустоту Таотэ", "Nine Nether Wyrm": "Дракон девяти преисподних",
    "Voidblade Mantis": "Богомол клинка пустоты", "Mirrorscale Basilisk": "Василиск с зеркальной чешуёй",
    "Abyssal Centipede": "Бездна-сороконожка", "Rakshasa": "Ракшаса", "Ordinary Body": "Обычное тело",
    "Robust Bones": "Крепкие кости", "Keen Spirit Sense": "Острое духовное чутьё", "Spirit-Sensitive Body": "Тело, чувствительное к духовной энергии",
    "Sickly Body": "Болезненное тело", "Withered Meridians": "Увядающие меридианы", "Innate Sword Body": "Врождённое тело меча",
    "Nine Yang Blazing Body": "Пылающее тело девяти ян", "Qi Gathering Grass": "Трава сбора ци",
    "Foundation Establishment Flower": "Цветок создания основы", "Heaven-Defying Lingzhi": "Линчжи, бросающий вызов небесам",
}


PHRASES.update({
    "Bloodfang Wolf":"Волк Кровавого Клыка", "Iron-Backed Boar":"Железноспинный кабан", "Jade Python":"Нефритовый питон", "Shadow Leopard":"Теневой леопард", "Thunder Ape":"Громовая обезьяна", "Frost Spider":"Ледяной паук", "Flood Dragon":"Водный дракон", "Flame Lion":"Огненный лев", "Golden Crow":"Золотой ворон", "Nine-Headed Serpent":"Девятиглавый змей", "Ancient Qilin":"Древний цилинь", "Kunpeng":"Куньпэн", "Celestial Thunder Dragon":"Небесный громовой дракон", "Heavenly Phoenix":"Небесный феникс", "Chaos Qilin":"Цилинь хаоса", "Thornback Pangolin":"Шипастый панголин", "Stone Rhinoceros":"Каменный носорог", "Blade-Feather Eagle":"Орёл со стальными перьями", "Ghostfire Fox":"Лисица призрачного пламени", "Mountain-Bearing Tortoise":"Черепаха, несущая гору", "Mirrorscale Basilisk":"Василиск с зеркальной чешуёй", "Ancient Treant":"Древний древесный дух", "Nine-Colour Deer":"Девятицветный олень", "Voidblade Mantis":"Богомол клинка пустоты", "Golden Cicada of Ages":"Золотая цикада веков", "White Tiger of the West":"Белый тигр Запада", "Vermilion Bird":"Алый феникс", "Ice Phoenix":"Ледяной феникс", "Void-Devouring Taotie":"Таотэ, пожирающий пустоту", "Nine Nether Wyrm":"Дракон девяти преисподних", "Candle Dragon":"Дракон свечи дня и ночи", "Black-and-White Fortune Cat":"Чёрно-белый кот удачи", "Hungry Ghost":"Голодный призрак", "Wandering Ghost":"Бродячий призрак", "Hopping Corpse":"Прыгающий мертвец", "Water Ghost":"Водяной призрак", "Bone Serpent of the Yellow Springs":"Костяной змей Жёлтых источников", "Ox-Head Guard":"Страж с головой быка", "Horse-Face Guard":"Страж с ликом коня", "Nether Raven":"Ворон преисподней", "Truth-Hearing Diting":"Дитин, слышащий истину", "Ghost King":"Король призраков", "Lesser Imp":"Малый бес", "Blood Demon":"Кровавый демон", "Brimstone Hound":"Серный пёс", "Asura Warrior":"Воин-асура", "Abyssal Centipede":"Сороконожка бездны", "Heart Demon":"Демон сердца", "Hellfire Wyvern":"Виверна адского пламени", "Rakshasa":"Ракшаса", "Abyss Behemoth":"Чудовище бездны", "Heavenly Demon":"Небесный демон",
    "Rending Bite":"Разрывающий укус", "Tusk Charge":"Атака бивнями", "Crushing Coil":"Сокрушительное кольцо", "Shadow Claw":"Теневой коготь", "Thunder Fist":"Громовой кулак", "Freezing Venom":"Леденящий яд", "Tidal Breath":"Приливное дыхание", "Inferno Roar":"Рёв преисподней", "Sun Fire":"Солнечное пламя", "Ninefold Venom":"Девятикратный яд", "Heavenly Judgement":"Небесная кара", "Abyssal Tide":"Прилив бездны", "Nine Heavens Thunder":"Гром девяти небес", "Nirvana Flame":"Пламя нирваны", "Primordial Stampede":"Первозданная лавина", "Rolling Thorn Crush":"Сокрушительный перекат шипов", "Boulder Charge":"Атака валуном", "Steel Feather Storm":"Буря стальных перьев", "Foxfire Bewitchment":"Чары лисьего пламени", "Mountain Stomp":"Топот горы", "Steel-Scale Lash":"Удар стальной чешуёй", "Root Snare":"Корневая ловушка", "Verdant Bloom":"Изумрудное цветение", "Space-Rending Scythe":"Коса, рассекающая пространство", "Song of Ten Thousand Summers":"Песнь десяти тысяч лет", "Killing Claw of the West":"Смертоносный коготь Запада", "Vermilion Flame":"Алое пламя", "Ten-Thousand-Li Frozen Sky":"Ледяное небо на десять тысяч ли", "All-Devouring Maw":"Всепоглощающая пасть", "Nine Nether Tide":"Прилив девяти преисподних", "Candle of Day and Night":"Свеча дня и ночи", "Beckoning Paw of Fortune":"Лапа, манящая удачу", "Ravenous Grasp":"Ненасытная хватка", "Grave Wail":"Погребальный вопль", "Stiff-Armed Strike":"Удар окоченевшей руки", "Drowning Embrace":"Утопляющее объятие", "Grave-Cold Coil":"Кольцо могильного холода", "Halberd of the Courts":"Алебарда чертогов", "Soul-Chaining Fork":"Трезубец, сковывающий души", "Omen Cry":"Крик дурного знамения", "Roar That Hears All Lies":"Рёв, слышащий любую ложь", "Wail of Ten Thousand Ghosts":"Вопль десяти тысяч призраков", "Spat Hellfire":"Плевок адского пламени", "Blood-Drinking Claw":"Коготь, пьющий кровь", "Brimstone Bite":"Укус серного пса", "Six-Armed Cleave":"Удар шести рук", "Hundred-Legged Venom":"Яд сотни ног", "Whisper of Your Own Doubt":"Шёпот твоих сомнений", "Abyssal Breath":"Дыхание бездны", "Man-Eating Talons":"Людоедские когти", "Trampling of the Abyss":"Топот бездны", "Gaze That Devours the Heavens":"Взгляд, пожирающий небеса",
    "Herb":"трава", "Ore":"руда", "Core":"ядро", "Metal":"металл", "Wood":"дерево", "Fire":"огонь", "Water":"вода", "Earth":"земля", "Wind":"ветер", "Lightning":"молния", "Ice":"лёд",
})
WORDS.update({"metal":"металл", "herb":"трава"})

VERBS = {
    "beckons away the fortune of": "отводит удачу от", "bewitches": "околдовывает", "bites": "кусает", "blooms around": "расцветает вокруг",
    "breathes a torrent at": "обрушивает поток на", "breathes fire on": "изрыгает пламя на", "breathes thunder at": "извергает гром на",
    "calls down judgement on": "обрушивает кару на", "charges": "бросается на", "claws": "терзает когтями", "cleaves": "рассекает",
    "coils around": "обвивает", "crashes down on": "обрушивается на", "cries death at": "возвещает смерть", "drags under": "утаскивает под воду",
    "drowns": "топит", "engulfs": "поглощает", "freezes the sky over": "сковывает небосвод льдом над", "gazes into": "всматривается в",
    "gnaws at": "грызёт", "gores": "пронзает клыками", "lashes": "хлещет", "opens its eyes on": "открывает глаза перед",
    "pounds": "обрушивает удар на", "rains steel feathers on": "осыпает стальными перьями", "rakes": "полосует когтями",
    "rends": "разрывает", "roars at": "рычит на", "roars fire at": "изрыгает пламя на", "rolls over": "катится по",
    "scorches": "опаляет", "scythes through the space around": "рассекает пространство вокруг", "sears": "испепеляет", "sings at": "поёт для",
    "sinks its fangs into": "впивается клыками в", "sinks nine sets of fangs into": "впивается девятью парами клыков в", "skewers": "пронзает",
    "snares": "опутывает", "spits fire at": "плюётся огнём в", "stamps the earth under": "топчет землю под", "stings": "жалит",
    "takes a bite out of": "откусывает кусок от", "tears at": "терзает", "tramples": "растаптывает", "wails at": "воет на", "whispers to": "шепчет",
}


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+|[^A-Za-z]+", text)


def transliterate(word: str) -> str:
    table = str.maketrans({"a":"а","b":"б","c":"к","d":"д","e":"е","f":"ф","g":"г","h":"х","i":"и","j":"дж","k":"к","l":"л","m":"м","n":"н","o":"о","p":"п","q":"к","r":"р","s":"с","t":"т","u":"у","v":"в","w":"в","x":"кс","y":"й","z":"з"})
    result = word.lower().translate(table)
    if word[:1].isupper():
        result = result[:1].upper() + result[1:]
    return result


def translate_label(text: str, *, title: bool = False) -> str:
    if text in PHRASES:
        return PHRASES[text]
    out = []
    for part in tokenize(text):
        if not part.isalpha():
            out.append(part.replace(" of ", " из "))
            continue
        if part.lower() in {"the", "a", "an"}:
            continue
        if part.lower() == "of":
            out.append("из")
            continue
        translated = WORDS.get(part.lower(), transliterate(part))
        if title and not out and translated and translated[0].islower():
            translated = translated[0].upper() + translated[1:]
        out.append(translated)
    return "".join(out).replace("  ", " ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("translated_dir", type=Path)
    parser.add_argument("--map", type=Path, help="also save final embedded source strings to the shared translation map")
    args = parser.parse_args()
    final_map = json.loads(args.map.read_text(encoding="utf-8")) if args.map else None
    fixes = 0
    for source in sorted(args.source_dir.rglob("*.json")):
        if source.name not in {"Cultivation.Sim.Data.beasts.json", "Cultivation.Sim.Data.materials.json", "Cultivation.Sim.Data.physiques.json"}:
            continue
        raw = source.read_text(encoding="utf-8")
        original = json.loads(raw[raw.find("["):])
        target = args.translated_dir / source.relative_to(args.source_dir)
        translated = json.loads(target.read_text(encoding="utf-8")) if target.exists() else json.loads(json.dumps(original))
        for original_obj, translated_obj in zip(original, translated):
            if not isinstance(original_obj, dict) or not isinstance(translated_obj, dict):
                continue
            for key in ("name", "attackName"):
                if isinstance(original_obj.get(key), str):
                    translated_obj[key] = translate_label(original_obj[key], title=True)
                    fixes += 1
            if isinstance(original_obj.get("verb"), str):
                translated_obj["verb"] = VERBS.get(original_obj["verb"], translate_label(original_obj["verb"]))
            for key in ("element", "kind"):
                # These values are parsed by the game as enum/schema identifiers.
                if isinstance(original_obj.get(key), str):
                    translated_obj[key] = original_obj[key]
            if final_map is not None:
                for key in ("name", "description", "attackName", "verb"):
                    source_value = original_obj.get(key)
                    translated_value = translated_obj.get(key)
                    if isinstance(source_value, str) and isinstance(translated_value, str) and source_value:
                        final_map[source_value] = translated_value
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(translated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if final_map is not None:
        args.map.write_text(json.dumps(final_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Normalized {fixes} embedded Russian labels")


if __name__ == "__main__":
    main()
