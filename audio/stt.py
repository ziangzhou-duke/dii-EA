import argparse
import numpy as np
import shlex
import subprocess
import sys
import wave
import json

from deepspeech import Model, version

try:
    from shhlex import quote
except ImportError:
    from pipes import quote


def convert_samplerate(audio_path, desired_sample_rate):
    sox_cmd = f'sox {quote(audio_path)} --type raw --bits 16 --channels 1 --rate {desired_sample_rate} --encoding ' \
              f'signed-integer --endian little --compression 0.0 --no-dither - '
    try:
        output = subprocess.check_output(shlex.split(sox_cmd), stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError('SoX returned non-zero status: {}'.format(e.stderr))
    except OSError as e:
        raise OSError(e.errno,
                      'SoX not found, use {}hz files or install it: {}'.format(desired_sample_rate, e.strerror))

    return desired_sample_rate, np.frombuffer(output, np.int16)


def metadata_to_string(metadata):
    return ''.join(token.text for token in metadata.tokens)


def words_from_candidate_transcript(metadata):
    word = ""
    word_list = []
    word_start_time = 0
    # Loop through each character
    for i, token in enumerate(metadata.tokens):
        # Append character to word if it's not a space
        if token.text != " ":
            if len(word) == 0:
                # Log the start time of the new word
                word_start_time = token.start_time

            word = word + token.text
        # Word boundary is either a space or the last character in the array
        if token.text == " " or i == len(metadata.tokens) - 1:
            word_duration = token.start_time - word_start_time

            if word_duration < 0:
                word_duration = 0

            each_word = dict()
            each_word["word"] = word
            each_word["start_time"] = round(word_start_time, 4)
            each_word["duration"] = round(word_duration, 4)

            word_list.append(each_word)
            # Reset
            word = ""
            word_start_time = 0

    return word_list


def metadata_json_output(metadata):
    json_result = dict()
    json_result["transcripts"] = [{
        "confidence": transcript.confidence,
        "words": words_from_candidate_transcript(transcript),
    } for transcript in metadata.transcripts]
    return json.dumps(json_result, indent=2)


class VersionAction(argparse.Action):
    def __init__(self, *args, **kwargs):
        super(VersionAction, self).__init__(nargs=0, *args, **kwargs)

    def __call__(self, *args, **kwargs):
        print('DeepSpeech ', version())
        exit(0)


def main():
    parser = argparse.ArgumentParser(description='Running DeepSpeech inference.')
    parser.add_argument('--model', required=True,
                        help='Path to the model (protocol buffer binary file)')
    parser.add_argument('--scorer', required=False,
                        help='Path to the external scorer file')
    parser.add_argument('--audio', required=True,
                        help='Path to the tests file to run (WAV format)')
    parser.add_argument('--beam_width', type=int,
                        help='Beam width for the CTC decoder')
    parser.add_argument('--lm_alpha', type=float,
                        help='Language model weight (lm_alpha). If not specified, use default from the scorer package.')
    parser.add_argument('--lm_beta', type=float,
                        help='Word insertion bonus (lm_beta). If not specified, use default from the scorer package.')
    parser.add_argument('--version', action=VersionAction,
                        help='Print version and exits')
    parser.add_argument('--extended', required=False, action='store_true',
                        help='Output string from extended metadata')
    parser.add_argument('--json', required=False, action='store_true',
                        help='Output json from metadata with timestamp of each word')
    parser.add_argument('--candidate_transcripts', type=int, default=3,
                        help='Number of candidate transcripts to include in JSON output')
    parser.add_argument('--hot_words', type=str,
                        help='Hot-words and their boosts.')
    args = parser.parse_args()

    print('Loading model from file {}'.format(args.model), file=sys.stderr)
    ds = Model(args.model)

    if args.beam_width:
        ds.setBeamWidth(args.beam_width)

    desired_sample_rate = ds.sampleRate()

    if args.scorer:
        print('Loading scorer from files {}'.format(args.scorer), file=sys.stderr)
        ds.enableExternalScorer(args.scorer)

        if args.lm_alpha and args.lm_beta:
            ds.setScorerAlphaBeta(args.lm_alpha, args.lm_beta)

    if args.hot_words:
        print('Adding hot-words', file=sys.stderr)
        for word_boost in args.hot_words.split(','):
            word, boost = word_boost.split(':')
            ds.addHotWord(word, float(boost))

    fin = wave.open(args.audio, 'rb')
    fs_orig = fin.getframerate()
    if fs_orig != desired_sample_rate:
        print(
            f'Warning: original sample rate ({fs_orig}) is different than {desired_sample_rate}hz. Resampling might '
            f'produce erratic speech recognition.',
            file=sys.stderr)
        fs_new, audio = convert_samplerate(args.audio, desired_sample_rate)
    else:
        audio = np.frombuffer(fin.readframes(fin.getnframes()), np.int16)

    fin.close()

    print('Running inference.', file=sys.stderr)
    if args.extended:
        print(metadata_to_string(ds.sttWithMetadata(audio, 1).transcripts[0]))
    elif args.json:
        print(metadata_json_output(ds.sttWithMetadata(audio, args.candidate_transcripts)))
    else:
        print(ds.stt(audio))


if __name__ == '__main__':
    main()
