#!/usr/bin/python2
#
# Copyright 2011 by Idiap Research Institute, http://www.idiap.ch
#
# See the file COPYING for the licence associated with this software.
#
# Author(s):
#   Phil Garner
#

from .. import ar
from .. import core
from .. import plot

import argparse
import sys
import numpy as np
import matplotlib.pyplot as plt


def parse_arguments(command_line_parameters):
    """Defines the command line parameters that are accepted."""

    # create parser
    parser = argparse.ArgumentParser(
        description='Displays an audio signal (wav file only)',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('filename', type=file,
                        help='Path to the file to process.')
    parser.add_argument('-t', '--type', type=str,
                        choices=('ar', 'psd', 'snr'), default='psd',
                        help='The type of spectrogram to generate')
    parser.add_argument('-n', '--no-show', action='store_true',
                        help='Do not call the show() method at the end of the script (mostly for testing purpose)')
    return parser.parse_args(command_line_parameters)


def spectrogram(args):

    # Load and process
    pcm = core.PulseCodeModulation()
    a = pcm.WavSource(args.filename)
    if (core.parameter('Pre', None)):
        a = core.ZeroFilter(a)
    framePeriod = pcm.seconds_to_period(0.01)
    frameSize = pcm.seconds_to_period(0.02, 'atleast')
    f = core.Frame(a, size=frameSize, period=framePeriod)
    w = core.nuttall(frameSize+1)
    w = np.delete(w, -1)
    wf = core.Window(f, w)
    ptype = core.parameter('Type', args.type)
    if ptype == 'psd':
        p = core.Periodogram(f)
        p = p[:,:p.shape[1]/2+1]
    elif ptype == 'ar':
        a = core.Autocorrelation(f)
        a, g = ar.ARLevinson(a, pcm.speech_ar_order())
        p = ar.ARSpectrum(a, g, nSpec=128)
    elif ptype == 'snr':
        p = core.Periodogram(f)
        n = core.Noise(p)
        p = core.SNRSpectrum(p, n)
        p = p[:,:p.shape[1]/2+1]
    else:
        raise runtime_error("Unsupported type for the spectrogram")

    # Draw it
    fig = plot.Figure(2, 1)
    p1 = fig.SpectrumPlot(p, pcm)
    p2 = fig.EnergyPlot(f, pcm)
    if args.no_show == False:
        fig.show()

    return 0

def main(command_line_parameters = sys.argv):
    """Executes the main function"""
    # do the command line parsing
    args = parse_arguments(command_line_parameters[1:])

    # perform face verification test
    return spectrogram(args)

if __name__ == "__main__":
    main()