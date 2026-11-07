"""Work out what kind of music a video is, from what its listing says.

A keyword match can tell you a title contains the word "house"; it cannot tell
you whether that is house music or a press briefing from the White House. This
module asks a short list of questions instead, the way you would when someone
describes a track you have not heard:

    Does it name the genre or a scene?   Does it name artists from it?
    What does it say about the bass, the drums, the vocals?
    Does it give a tempo?                 Does it name a label or a place?

Each genre answers those questions with its own vocabulary. Every answer that
lands adds evidence, but not all answers are equally useful: a word that turns
up in half the library ("mix") says far less than one that turns up in twenty
videos. So each hit is weighted by how rare the phrase is across the actual
index, which is the part learned from the library rather than baked in here.

The result is a genre, a confidence that reflects how decisive the evidence is
(not a probability), and the answers it used, so the guess can be checked.
"""

import math
import re
from typing import Dict, List, Optional

# How much a single hit in each kind of answer counts. Naming the genre outright
# is strong; a mood word or a passing instrument mention is a hint.
PROBE_WEIGHTS = {
    'genre': 3.0,
    'scene': 2.2,
    'artists': 1.9,
    'labels': 1.6,
    'bass': 1.6,
    'drums': 1.4,
    'vocals': 1.3,
    'instruments': 1.1,
    'place': 1.0,
    'mood': 0.6,
}

# The question each kind of answer is answering, in the order it gets asked.
PROBE_QUESTIONS = {
    'genre': 'Does the listing name the genre?',
    'scene': 'Does it name a scene or subgenre?',
    'artists': 'Does it name artists from that scene?',
    'labels': 'Does it name a label?',
    'bass': 'What does it say about the bass?',
    'drums': 'What does it say about the drums?',
    'vocals': 'What does it say about the vocals?',
    'instruments': 'Which instruments does it mention?',
    'place': 'Does it name a place associated with the sound?',
    'mood': 'What mood does it describe?',
}

GENRES = {
    'dubstep': {
        'tempo': [(136, 144)],
        'signals': {
            'genre': ['dubstep', 'brostep', 'riddim', 'drumstep', 'bass music'],
            'scene': ['deep dubstep', 'tearout', 'half-time', 'halftime', 'badman sound', '140'],
            'bass': ['wobble', 'reese bass', 'growl', 'sub bass', 'sub-bass', 'bass drop', 'mid-range bass'],
            'drums': ['half time', 'snare'],
            'vocals': ['vocoder', 'chopped vocal'],
            'artists': ['skrillex', 'excision', 'borgore', 'zomboy', 'rusko', 'caspa', 'loefah',
                        'skream', 'benga', 'subtronics', 'virtual riot', 'svdden death', 'space laces'],
            'labels': ['deep medi', 'tempa', 'never say die', 'disciple', 'monstercat'],
            'place': ['croydon', 'bristol'],
            'mood': ['dark', 'aggressive'],
        },
    },
    'drum & bass / jungle': {
        'tempo': [(165, 180)],
        'signals': {
            'genre': ['drum and bass', 'drum & bass', 'dnb', 'd&b', 'jungle', 'junglist', 'ragga jungle'],
            'scene': ['liquid dnb', 'neurofunk', 'jump up', 'darkstep', 'atmospheric dnb'],
            'bass': ['reese', 'sub bass', 'roller'],
            'drums': ['amen break', 'breakbeat', 'breaks', 'two-step'],
            'vocals': ['mc', 'ragga', 'patois'],
            'artists': ['andy c', 'goldie', 'ltj bukem', 'shy fx', 'high contrast', 'noisia',
                        'sub focus', 'hospital', 'hype', 'dillinja', 'roni size'],
            'labels': ['hospital records', 'ram records', 'metalheadz', 'shogun audio', 'viper'],
            'place': ['london', 'bristol'],
            'mood': ['rolling', 'energetic'],
        },
    },
    'house': {
        'tempo': [(118, 128)],
        'signals': {
            'genre': ['house music', 'deep house', 'tech house', 'acid house', 'garage house'],
            'scene': ['deep house', 'tech house', 'acid house', 'chicago house', 'afro house', 'soulful house'],
            'drums': ['four on the floor', 'four-to-the-floor', 'piano riff'],
            'bass': ['walking bass', 'bassline'],
            'vocals': ['diva', 'soul vocal'],
            'instruments': ['piano', 'organ', 'rhodes'],
            'artists': ['frankie knuckles', 'larry heard', 'kerri chandler', 'disclosure',
                        'mk', 'todd terry', 'honey dijon'],
            'labels': ['defected', 'strictly rhythm', 'trax records', 'toolroom'],
            'place': ['chicago', 'new york', 'ibiza'],
            'mood': ['groovy', 'uplifting', 'warm'],
        },
    },
    'techno': {
        'tempo': [(125, 140)],
        'signals': {
            'genre': ['techno', 'tech-house'],
            'scene': ['minimal techno', 'industrial techno', 'detroit techno', 'acid techno', 'hardgroove'],
            'drums': ['kick drum', 'four on the floor', 'four-to-the-floor', '909'],
            'bass': ['rumbling bass', 'sub kick'],
            'instruments': ['modular', 'synthesizer', 'drum machine', '303'],
            'artists': ['jeff mills', 'ben klock', 'marcel dettmann', 'amelie lens', 'charlotte de witte',
                        'adam beyer', 'richie hawtin', 'surgeon', 'dax j'],
            'labels': ['ostgut ton', 'drumcode', 'monnom black', 'klockworks'],
            'place': ['detroit', 'berlin', 'tresor'],
            'mood': ['hypnotic', 'dark', 'relentless'],
        },
    },
    'trance': {
        'tempo': [(130, 145)],
        'signals': {
            'genre': ['trance', 'psytrance', 'progressive trance', 'uplifting trance'],
            'scene': ['psytrance', 'goa trance', 'uplifting', 'progressive trance'],
            'bass': ['rolling bassline'],
            'instruments': ['supersaw', 'arpeggio', 'arpeggiated'],
            'artists': ['armin van buuren', 'tiesto', 'above & beyond', 'ferry corsten',
                        'paul van dyk', 'astrix', 'aly & fila'],
            'labels': ['anjunabeats', 'armada', 'asot', 'black hole'],
            'place': ['ibiza', 'goa'],
            'mood': ['euphoric', 'emotional', 'energetic'],
        },
    },
    'hip hop / rap': {
        'tempo': [(80, 100), (60, 75)],
        'signals': {
            'genre': ['hip hop', 'hip-hop', 'rap', 'rapper', 'boom bap'],
            'scene': ['boom bap', 'g-funk', 'drill', 'grime', 'conscious hip hop', 'old school'],
            'drums': ['breakbeat', 'sample flip', 'kick snare'],
            'bass': ['808', 'sub bass'],
            'vocals': ['freestyle', 'verse', 'bars', 'diss track', 'cypher'],
            'artists': ['nas', 'jay-z', 'kendrick lamar', 'eminem', 'wu-tang', 'rakim',
                        'mf doom', 'j dilla', 'madlib', 'dr dre', 'snoop dogg'],
            'labels': ['stones throw', 'top dawg', 'aftermath', 'tommy boy'],
            'place': ['bronx', 'compton', 'atlanta', 'detroit'],
            'mood': ['braggadocio', 'laid back'],
        },
    },
    'trap': {
        'tempo': [(130, 150), (70, 80)],
        'signals': {
            'genre': ['trap', 'trap music', 'phonk'],
            'scene': ['drill', 'phonk', 'rage', 'dark trap'],
            'drums': ['hi-hat rolls', 'hi-hat', 'hat rolls', 'triplet'],
            'bass': ['808', 'sliding 808'],
            'vocals': ['autotune', 'ad-libs', 'adlibs'],
            'artists': ['gucci mane', 'future', 'migos', 'travis scott', 'young thug',
                        'chief keef', 'playboi carti'],
            'labels': ['quality control', 'freebandz', 'almo sounds'],
            'place': ['atlanta', 'chicago'],
            'mood': ['menacing', 'hazy'],
        },
    },
    'reggae / dancehall': {
        'tempo': [(60, 90), (95, 110)],
        'signals': {
            'genre': ['reggae', 'dancehall', 'ragga', 'ska', 'rocksteady', 'roots reggae'],
            'scene': ['roots reggae', 'dub poetry', 'bashment', 'ragga', 'lovers rock'],
            'drums': ['one drop', 'skank', 'steppers'],
            'bass': ['bassline', 'dub bass'],
            'vocals': ['patois', 'toasting', 'deejay', 'chant'],
            'instruments': ['horn section', 'melodica', 'nyabinghi'],
            'artists': ['bob marley', 'peter tosh', 'bunny wailer', 'shabba ranks', 'buju banton',
                        'capleton', 'sizzla', 'chronixx', 'sean paul', 'damian marley'],
            'labels': ['island records', 'studio one', 'greensleeves', 'vp records'],
            'place': ['kingston', 'jamaica', 'trenchtown'],
            'mood': ['spiritual', 'sunny', 'uplifting'],
        },
    },
    'dub': {
        'tempo': [(60, 90)],
        'signals': {
            'genre': ['dub', 'dub music', 'dub reggae'],
            'scene': ['dub', 'steppers', 'dubwise', 'sound system'],
            'bass': ['deep bass', 'sub bass', 'bass delay'],
            'drums': ['one drop', 'echo', 'delay'],
            'instruments': ['melodica', 'spring reverb', 'tape delay'],
            'artists': ['king tubby', 'lee perry', 'scientist', 'mad professor', 'sly and robbie'],
            'labels': ['on-u sound', 'ariwa', 'blood and fire'],
            'place': ['kingston', 'jamaica'],
            'mood': ['spacious', 'hypnotic'],
        },
    },
    'ambient / chill': {
        'tempo': [(50, 90)],
        'signals': {
            'genre': ['ambient', 'drone', 'new age', 'chillout', 'downtempo'],
            'scene': ['ambient', 'drone', 'field recording', 'beatless', 'meditation'],
            'instruments': ['modular', 'synthesizer', 'tape loop', 'piano', 'strings'],
            'artists': ['brian eno', 'aphex twin', 'boards of canada', 'biosphere', 'steve roach',
                        'stars of the lid', 'hammock'],
            'labels': ['warp', 'kranky', '12k', 'ghostly'],
            'place': [],
            'mood': ['calm', 'meditative', 'sleep', 'study', 'atmospheric'],
        },
    },
    'lo-fi': {
        'tempo': [(70, 90)],
        'signals': {
            'genre': ['lofi', 'lo-fi', 'lo fi', 'chillhop'],
            'scene': ['lofi hip hop', 'chillhop', 'jazzhop', 'study beats'],
            'drums': ['vinyl crackle', 'dusty drums', 'tape hiss'],
            'instruments': ['rhodes', 'piano', 'vinyl'],
            'artists': ['nujabes', 'jinsang', 'idealism', 'chilledcow'],
            'labels': ['chillhop records', 'lofi records'],
            'mood': ['relaxing', 'study', 'sleepy', 'nostalgic', 'rainy'],
        },
    },
    'rock / metal': {
        'tempo': [(100, 160), (170, 220)],
        'signals': {
            'genre': ['rock', 'metal', 'punk', 'hardcore punk', 'grunge', 'heavy metal'],
            'scene': ['hard rock', 'classic rock', 'death metal', 'black metal', 'thrash',
                      'nu metal', 'post-rock', 'shoegaze', 'emo'],
            'drums': ['double kick', 'blast beat', 'drum fill'],
            'bass': ['distorted bass'],
            'vocals': ['screaming', 'growls', 'falsetto', 'shouted'],
            'instruments': ['electric guitar', 'guitar solo', 'distortion', 'riffs', 'pedalboard'],
            'artists': ['metallica', 'nirvana', 'led zeppelin', 'black sabbath', 'slayer',
                        'tool', 'radiohead', 'foo fighters', 'iron maiden', 'pantera'],
            'labels': ['sub pop', 'roadrunner', 'earache', 'dischord'],
            'place': ['seattle', 'sheffield'],
            'mood': ['angry', 'anthemic', 'heavy'],
        },
    },
    'pop': {
        'tempo': [(95, 130)],
        'signals': {
            'genre': ['pop music', 'pop song', 'pop star', 'k-pop', 'j-pop', 'synth-pop', 'synthpop'],
            'scene': ['k-pop', 'j-pop', 'europop', 'teen pop', 'dance pop'],
            'vocals': ['hook', 'chorus', 'harmonies'],
            'instruments': ['synth', 'drum machine'],
            'artists': ['taylor swift', 'ariana grande', 'dua lipa', 'bts', 'weeknd',
                        'billie eilish', 'madonna', 'michael jackson'],
            'labels': ['interscope', 'republic records', 'atlantic records'],
            'place': ['stockholm', 'seoul'],
            'mood': ['catchy', 'feel good', 'romantic'],
        },
    },
    'jazz / soul / funk': {
        'tempo': [(60, 140)],
        'signals': {
            'genre': ['jazz', 'soul', 'funk', 'bossa nova', 'swing', 'blues'],
            'scene': ['bebop', 'hard bop', 'free jazz', 'smooth jazz', 'neo soul', 'motown', 'afrobeat'],
            'drums': ['swing', 'brushes', 'shuffle'],
            'bass': ['walking bass', 'upright bass'],
            'vocals': ['scat', 'crooner'],
            'instruments': ['saxophone', 'trumpet', 'double bass', 'organ', 'electric piano',
                            'hammond', 'trombone', 'clarinet'],
            'artists': ['miles davis', 'john coltrane', 'bill evans', 'herbie hancock',
                        'james brown', 'stevie wonder', 'marvin gaye', 'etta james',
                        'nina simone', 'curtis mayfield', 'fela kuti'],
            'labels': ['blue note', 'impulse', 'motown', 'stax', 'verve'],
            'place': ['new orleans', 'chicago', 'memphis', 'new york'],
            'mood': ['soulful', 'swinging', 'smoky'],
        },
    },
    'classical': {
        'tempo': [],
        'signals': {
            'genre': ['classical', 'orchestra', 'symphony', 'opera', 'baroque', 'chamber music'],
            'scene': ['symphony', 'concerto', 'sonata', 'string quartet', 'choral', 'requiem'],
            'instruments': ['violin', 'cello', 'piano', 'harpsichord', 'organ', 'flute', 'harp', 'choir'],
            'artists': ['bach', 'mozart', 'beethoven', 'chopin', 'debussy', 'ravel',
                        'mahler', 'brahms', 'vivaldi', 'rachmaninoff'],
            'labels': ['deutsche grammophon', 'decca', 'naxos', 'hyperion'],
            'place': ['vienna', 'leipzig'],
            'mood': ['solemn', 'grand', 'pastoral'],
        },
    },
    'latin': {
        'tempo': [(85, 110)],
        'signals': {
            'genre': ['salsa', 'bachata', 'merengue', 'cumbia', 'reggaeton', 'latin', 'bossa nova'],
            'scene': ['salsa', 'bachata', 'cumbia', 'reggaeton', 'perreo', 'banda', 'norteno'],
            'drums': ['clave', 'timbales', 'dembow', 'congas'],
            'instruments': ['accordion', 'trumpet', 'marimba', 'guitarra', 'requinto'],
            'artists': ['celia cruz', 'bad bunny', 'j balvin', 'daddy yankee', 'shakira',
                        'los angeles azules', 'tito puente'],
            'labels': ['fania', 'rimas', 'discos musart'],
            'place': ['san juan', 'havana', 'medellin', 'mexico'],
            'mood': ['festive', 'romantic', 'danceable'],
        },
    },
    'country / folk': {
        'tempo': [(70, 120)],
        'signals': {
            'genre': ['country', 'bluegrass', 'folk', 'americana', 'western swing'],
            'scene': ['outlaw country', 'bluegrass', 'americana', 'folk', 'appalachian'],
            'instruments': ['banjo', 'fiddle', 'pedal steel', 'acoustic guitar', 'harmonica', 'mandolin'],
            'artists': ['johnny cash', 'dolly parton', 'willie nelson', 'hank williams',
                        'doc watson', 'john prine', 'chris stapleton'],
            'labels': ['rounder', 'sugar hill', 'nashville'],
            'place': ['nashville', 'appalachia', 'texas'],
            'mood': ['heartfelt', 'storytelling', 'wistful'],
        },
    },
}

# Words that suggest the listing is about music at all. Without one of these and
# without a genre signal, a video is left unlabelled rather than guessed at.
MUSIC_CUES = [
    'music', 'song', 'songs', 'remix', 'mix', 'mixtape', 'dj', 'track', 'album',
    'single', 'ep', 'beat', 'beats', 'instrumental', 'lyrics', 'karaoke', 'live set',
    'concert', 'band', 'singer', 'vocal', 'vocals', 'audio', 'ost', 'soundtrack',
    'bpm', 'acoustic', 'orchestra', 'piano', 'guitar', 'drums', 'choir', 'genre',
    'playlist', 'radio', 'studio session', 'bootleg', 'edit', 'rework',
]

TEMPO_RE = re.compile(r'\b(\d{2,3})\s*(?:bpm|beats per minute)\b', re.IGNORECASE)

# Words that put a listing in a workshop, a catalogue or a factory rather than in
# music. "Metal Cutting" and "Gable Trim" are not heavy metal; a listing that
# also talks about music overrides these.
NON_MUSIC_MARKERS = [
    'cutting', 'welding', 'fabrication', 'installation', 'roofing', 'scrap',
    'manufactur', 'supplier', 'wholesale', 'in stock', 'sheet metal', 'alloy',
    'gable', 'trim', 'pipe', 'drill bit', 'hand tool', 'fixtures', 'catalogue',
]


def _phrase_pattern(phrase: str) -> re.Pattern:
    """Match a phrase on both word boundaries.

    Without the trailing one, "dub" matches "dubstep" and every dubstep track
    gets labelled as dub; without the leading one, "house" matches "warehouse".
    """
    escaped = re.escape(phrase).replace(r'\ ', r'\s+')
    # Allow the plural so "pop song" still matches "pop songs".
    plural = 's?' if phrase[-1].isalpha() else ''
    return re.compile(r'(?<![a-z0-9])' + escaped + plural + r'(?![a-z0-9])', re.IGNORECASE)


def _group_evidence(findings: List[Dict]) -> List[Dict]:
    """One line per question, so repeated answers read as a list.

    Three mood words used to appear as three identical questions; they belong
    together: "What mood does it describe? mentions calm, sleep, study".
    """
    order: List[str] = []
    grouped: Dict[str, Dict] = {}
    for item in findings:
        question = item['question']
        if question not in grouped:
            grouped[question] = {'question': question, 'parts': [], 'points': 0.0, 'plain': False}
            order.append(question)
        entry = grouped[question]
        entry['parts'].append(item['term'])
        entry['points'] += item['points']
        entry['plain'] = entry['plain'] or item.get('plain', False)

    result = []
    for question in order:
        entry = grouped[question]
        if entry['plain']:
            text = entry['parts'][0]
        else:
            text = 'mentions ' + ', '.join(f'"{part}"' for part in entry['parts'])
        result.append({
            'question': question,
            'answer': text,
            'points': round(entry['points'], 2),
        })
    result.sort(key=lambda item: item['points'], reverse=True)
    return result


class MusicGenreModel:
    """Asks a fixed list of questions about a listing and weighs the answers."""

    def __init__(self, documents: Optional[List[str]] = None):
        self.n_docs = 0
        self.phrase_df: Dict[str, int] = {}
        self._patterns = {}
        for genre, profile in GENRES.items():
            for kind, phrases in profile['signals'].items():
                for phrase in phrases:
                    self._patterns.setdefault(phrase, _phrase_pattern(phrase))
        if documents:
            self.fit(documents)

    def fit(self, documents: List[str]) -> None:
        """Count how often each phrase appears in the library.

        A phrase found in most listings is a weak clue, so this is what makes the
        weighting reflect this library instead of a fixed guess.
        """
        texts = [doc or '' for doc in documents]
        self.n_docs = len(texts)
        counts = {phrase: 0 for phrase in self._patterns}
        for text in texts:
            lowered = text.lower()
            for phrase, pattern in self._patterns.items():
                if pattern.search(lowered):
                    counts[phrase] += 1
        self.phrase_df = counts

    def _rarity(self, phrase: str, floor: float = 0.2) -> float:
        """Scale a phrase by how rare it is here, never below `floor`.

        A genre word stays believable even when the library holds a lot of that
        genre ("reggae" is still a genre name in a library full of reggae), while
        an incidental word loses nearly all its weight once it is everywhere.
        """
        if not self.n_docs:
            return 1.0
        df = self.phrase_df.get(phrase, 0)
        if df <= 0:
            # Never seen in the library, so its rarity cannot be judged yet.
            return 0.9
        idf = math.log((self.n_docs + 1) / (df + 1)) / math.log(self.n_docs + 1)
        idf = max(0.0, min(1.0, idf))
        return floor + (1.0 - floor) * idf

    def infer(self, title: str = '', description: str = '', tags: str = '') -> Optional[Dict]:
        """Return the likeliest genre with its evidence, or None when unsure."""
        title = title or ''
        description = description or ''
        tags = tags or ''
        text = f'{title} {description} {tags}'.lower()
        if not text.strip():
            return None

        has_music_cue = any(
            re.search(r'(?<![a-z0-9])' + re.escape(cue) + r'(?![a-z0-9])', text)
            for cue in MUSIC_CUES
        )

        bpm = None
        tempo_match = TEMPO_RE.search(text)
        if tempo_match:
            value = int(tempo_match.group(1))
            if 40 <= value <= 240:
                bpm = value

        scores: Dict[str, float] = {}
        evidence: Dict[str, List[Dict]] = {}

        for genre, profile in GENRES.items():
            total = 0.0
            findings: List[Dict] = []
            for kind, phrases in profile['signals'].items():
                for phrase in phrases:
                    if not phrase:
                        continue
                    pattern = self._patterns.get(phrase) or _phrase_pattern(phrase)
                    if not pattern.search(text):
                        continue
                    floor = 0.7 if kind in ('genre', 'scene') else 0.2
                    points = PROBE_WEIGHTS.get(kind, 1.0) * self._rarity(phrase, floor)
                    total += points
                    findings.append({
                        'kind': kind,
                        'question': PROBE_QUESTIONS.get(kind, 'What else does it say?'),
                        'term': phrase,
                        'points': round(points, 2),
                    })
            if bpm:
                for low, high in profile.get('tempo', []):
                    if low <= bpm <= high:
                        total += 1.4
                        findings.append({
                            'kind': 'tempo',
                            'question': 'Does it give a tempo?',
                            'term': f'{bpm} bpm, which is where {genre} usually sits '
                                    f'({low}-{high} bpm)',
                            'plain': True,
                            'points': 1.4,
                        })
                        break
            if total > 0:
                scores[genre] = total
                evidence[genre] = findings

        if not scores:
            return None

        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_genre, best_score = ordered[0]
        runner_up = ordered[1][1] if len(ordered) > 1 else 0.0

        # Below this the listing simply does not say enough to name a genre.
        if best_score < 2.0:
            return None
        # A workshop or catalogue listing that happens to name a metal is not
        # music, unless it plainly talks about music too.
        strong_cues = ('music', 'song', 'remix', 'mix', 'album', 'band', 'dj',
                       'concert', 'lyrics', 'instrumental', 'playlist')
        if not any(
            re.search(r'(?<![a-z0-9])' + re.escape(cue) + r's?(?![a-z0-9])', text)
            for cue in strong_cues
        ) and any(marker in text for marker in NON_MUSIC_MARKERS):
            return None

        confidence = best_score / (best_score + 0.4 * runner_up + 1.0)
        # A listing that talks about music at all is less likely to be an
        # unrelated page that happens to contain a genre word.
        if has_music_cue:
            confidence += 0.06
        confidence = max(0.0, min(0.98, confidence))

        findings = sorted(evidence[best_genre], key=lambda item: item['points'], reverse=True)
        return {
            'genre': best_genre,
            'confidence': round(confidence, 2),
            'evidence': _group_evidence(findings)[:4],
            'alternatives': [
                {'genre': name, 'score': round(value, 2)}
                for name, value in ordered[1:4]
            ],
            'bpm': bpm,
        }
