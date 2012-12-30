#!/usr/bin/python2
# -*- coding: utf-8 -*-
#
# Copyright 2012 by Idiap Research Institute, http://www.idiap.ch
#
# See the file COPYING for the licence associated with this software.
#
# Author(s):
#   Phil Garner, May 2012
#
import ssp
from ssp import *
from optparse import OptionParser
from os.path import splitext

# Command line
op = OptionParser(usage="usage: %prog [options] [inFile outFile]")
op.add_option("-r", dest="rate", default='16000',
              help="Sample rate")
op.add_option("-f", dest="fileList",
              help="List of input output file pairs")
op.add_option("-m", dest="framePeriod", action="store", type="int",
              help="Frame period")
op.add_option("-e", dest="encode", action="store_true", default=False,
              help="Encode source files")
op.add_option("-p", dest="pitch", action="store_true", default=False,
              help="Encode source files, linear cont. pitch only")
op.add_option("-d", dest="decode", action="store_true", default=False,
              help="Decode source files")
op.add_option("-o", dest="ola", action="store_false", default=True,
              help="Concatenate frames (i.e., don't use OLA)")
op.add_option("-x", dest="excitation", action="store_true", default=False,
              help="Output excitation waveform instead of encoding")
(opt, arg) = op.parse_args()

# For excitation we need to disable OLA
if opt.excitation:
    opt.ola = False

# Fall back on command line input and output
pairs = []
if opt.fileList:
    with open(opt.fileList) as f:
        pairs = f.readlines()
else:
    if len(arg) != 2:
        print "Need two args if no file list"
        exit(1)
    pairs = [ ' '.join(arg) ]

lpOrder = {
    8000: 10,
    16000: 24,
    22050: 24
}


def encode(a, pcm):
    """
    Encode a speech waveform.  The encoding framers (frames and pitch)
    pad the frames so that the first frame is centered on sample zero.
    This is consistent with STRAIGHT and SPTK (I hope!).  At least, it
    means the pitch can have longer frame lengths and still align with
    the OLA'd frames.
    """
    if opt.ola:
        frameSize = pcm.seconds_to_period(0.025, 'atleast') # 25ms frame size
    else:
        frameSize = framePeriod
    pitchSize = pcm.seconds_to_period(0.1, 'atmost')
    print "Encoding with period", framePeriod, "size", frameSize, \
          "and pitch window", pitchSize

    # First the pitch as it's on the unaltered waveform.  The frame
    # should be long with no window.  1024 at 16 kHz is 64 ms.
    pf = Frame(a, size=pitchSize, period=framePeriod)
    pitch, hnr = ACPitch(pf, pcm)

    # Pre-emphasis
    pre = ssp.parameter("Pre", None)
    if pre is not None:
        a = PoleFilter(a, pre) / 5

    # Keep f around after the function so the decoder can do a
    # reference decoding on the real excitaton.
    global f
    f = Frame(a, size=frameSize, period=framePeriod)
    #aw = np.hanning(frameSize+1)
    aw = ssp.nuttall(frameSize+1)
    aw = np.delete(aw, -1)
    w = Window(f, aw)
    ac = Autocorrelation(w)
    lp = ssp.parameter('AR', 'levinson')
    if lp == 'levinson':
        ar, g = ARLevinson(ac, lpOrder[r])
    elif lp == 'ridge':
        ar, g = ARRidge(ac, lpOrder[r], 0.03)
    elif lp == 'lasso':
        ar, g = ARLasso(ac, lpOrder[r], 5)
    elif lp == 'sparse':
        ar, g = ARSparse(f, lpOrder[r], ssp.parameter('Gamma', 1.414))

    if False:
        fig = Figure(5, 1)
        #stddev = np.sqrt(kVar)
        sPlot = fig.subplot()
        sPlot.plot(pitch, 'c')
        #sPlot.plot(kPitch + stddev, 'b')
        #sPlot.plot(kPitch - stddev, 'b')
        sPlot.set_xlim(0, len(pitch))
        sPlot.set_ylim(0, 500)
        plt.show()

    return (ar, g, pitch, hnr)


def decode((ar, g, pitch, hnr)):
    """
    Decode a speech waveform.
    """
    nFrames = len(ar)
    assert(len(g) == nFrames)
    assert(len(pitch) == nFrames)
    assert(len(hnr) == nFrames)

    # The original framer padded the ends so the number of samples to
    # synthesise is a bit less than you might think
    if opt.ola:
        frameSize = framePeriod * 2
        nSamples = framePeriod * (nFrames-1)
    else:
        frameSize = framePeriod
        nSamples = frameSize * (nFrames-1)

    ex = ssp.parameter('Excitation', 'synth')

    # Use the original AR residual; it should be a very good
    # reconstruction.
    if ex == 'ar':
        e = ARExcitation(f, ar, g)

    # Just noise.  This is effectively a whisper synthesis.
    elif ex == 'noise':
        e = np.random.normal(size=f.shape)

    # Just harmonics, and with a fixed F0.  This is the classic robot
    # syntheisis.
    elif ex == 'robot':
        ew = np.zeros(nSamples)
        period = int(1.0 / 200 * r)
        for i in range(0, len(ew), period):
            ew[i] = period
        e = Frame(ew, size=frameSize, period=framePeriod)        

    # Synthesise harmonics plus noise in the ratio suggested by the
    # HNR.
    elif ex == 'synth':
        # Harmonic part
        mperiod = int(1.0 / np.mean(pitch) * r)
        gm = GlottalModel(ssp.parameter('Pulse', 'impulse'))
        pr, pg = pulse_response(gm, pcm, period=mperiod, order=lpOrder[r])
        h = np.zeros(nSamples)
        i = 0
        frame = 0
        while i < nSamples and frame < len(pitch):
            period = int(1.0 / pitch[frame] * r)
            if i + period > nSamples:
                break
            weight = np.sqrt(hnr[frame] / (hnr[frame] + 1))
            h[i:i+period] = gm.pulse(period, pcm) * weight
            i += period
            frame = i // framePeriod
        h = ARExcitation(h, pr, 1.0)
        fh = Frame(h, size=frameSize, period=framePeriod)

        # Noise part
        n = np.random.normal(size=nSamples)
        n = ZeroFilter(n, 1.0) # Include the radiation impedance
        fn = Frame(n, size=frameSize, period=framePeriod)
        for i in range(len(fn)):
            fn[i] *= np.sqrt(1.0 / (hnr[i] + 1))

        hgain = ssp.parameter("HGain", 1.0)
        e = fn + fh * hgain

    # Like harmonics plus noise, but with explicit sinusoids instead
    # of time domain impulses.
    elif ex == 'sine':
        order = 20
        sine = Harmonics(r, order)
        h = np.zeros(nSamples)
        for i in range(0, len(h)-framePeriod, framePeriod):
            frame = i // framePeriod
            period = int(1.0 / pitch[frame] * r)
            weight = np.sqrt(hnr[frame] / (hnr[frame] + 1))
            h[i:i+framePeriod] = ( sine.sample(pitch[frame], framePeriod)
                                      * weight )
        fh = Frame(h, size=frameSize, period=framePeriod)
        n = np.random.normal(size=nSamples)
        fn = Frame(n, size=frameSize, period=framePeriod)
        for i in range(len(fn)):
            fn[i] *= np.sqrt(1.0 / (hnr[i] + 1))
        e = fn + fh*10

    # High order linear prediction.  Synthesise the harmonics using
    # noise to excite a high order polynomial with roots resembling
    # harmonics.
    elif ex == 'holp':
        # Some noise
        n = np.random.normal(size=nSamples)
        fn = Frame(n, size=frameSize, period=framePeriod)

        # Use the noise to excite a high order AR model
        fh = np.ndarray(fn.shape)
        for i in range(len(fn)):
            hoar = ARHarmonicPoly(pitch[i], r, 0.7)
            fh[i] = ARResynthesis(fn[i], hoar, 1.0 / linalg.norm(hoar)**2)
            print i, pitch[i], linalg.norm(hoar), np.min(fh[i]), np.max(fh[i])
            print ' ', np.min(hoar), np.max(hoar)
            # fh[i] *= np.sqrt(r / pitch[i]) / linalg.norm(fh[i])
            # fh[i] *= np.sqrt(hnr[i] / (hnr[i] + 1))

        # Weight the noise as for the other methods
        for i in range(len(fn)):
            fn[i] *= np.sqrt(1.0 / (hnr[i] + 1))
        e = fh # fn + fh*30
        
    # Shaped excitation.  The pulses are shaped by a filter to have a
    # rolloff, then added to the noise.  The resulting signal is
    # flattened using AR.
    elif ex == 'shaped':
        # Harmonic part
        gm = GlottalModel(ssp.parameter('Pulse', 'impulse'))
        h = np.zeros(nSamples)
        i = 0
        frame = 0
        while i < nSamples and frame < len(pitch):
            period = int(1.0 / pitch[frame] * r)
            if i + period > nSamples:
                break
            weight = np.sqrt(hnr[frame] / (hnr[frame] + 1))
            h[i:i+period] = gm.pulse(period, pcm) * weight
            i += period
            frame = i // framePeriod

        # Filter to mimic the glottal pulse
        #pole = ssp.parameter("Pole", None)
        pole = None
        if pole is not None:
            #h = PoleFilter(h, pole)
            #h = PoleFilter(h, pole)
            h = ZeroFilter(h, -1.0)
            h = ZeroFilter(h, -0.5)
            h = ZeroFilter(h, 1.0)
            h = PolePairFilter(h, pole, pcm.hertz_to_radians(np.mean(pitch)))
        fh = Frame(h, size=frameSize, period=framePeriod)

        # Noise part
        n = np.random.normal(size=nSamples)
        zero = ssp.parameter("NoiseZero", 1.0)
        n = ZeroFilter(n, zero) # Include the radiation impedance
        fn = Frame(n, size=frameSize, period=framePeriod)
        for i in range(len(fn)):
            fn[i] *= np.sqrt(1.0 / (hnr[i] + 1))

        # Combination
        assert(len(fh) == len(fn))        
        hgain = ssp.parameter("HGain", 1.0)
        e = fn + fh * hgain
        hnw = np.hanning(frameSize)
        for i in range(len(e)):
            ep = Window(e[i], hnw)
            #ep = e[i]
            eac = Autocorrelation(ep)
            ea, eg = ARLevinson(eac, order=lpOrder[r])
            e[i] = ARExcitation(e[i], ea, eg)

    else:
        print "Unknown synthesis method"
        exit

    if opt.excitation:
        s = e.flatten('C')/frameSize
    else:
        s = ARResynthesis(e, ar, g)
        if opt.ola:
            # Asymmetric window for OLA
            sw = np.hanning(frameSize+1)
            sw = np.delete(sw, -1)
            s = Window(s, sw)
            s = OverlapAdd(s)
        else:
            s = s.flatten('C')
            
    return s

#
# Main loop over the file list
#
r = int(opt.rate)
pcm = PulseCodeModulation(r)
if opt.framePeriod:
    framePeriod = opt.framePeriod
else:
    framePeriod = pcm.seconds_to_period(0.005, 'atleast') # 5ms period

for pair in pairs:
    loadFile, saveFile = pair.strip().split()

    # Neither flag - assume a best effort copy
    if not (opt.encode or opt.decode or opt.pitch):
        a = pcm.WavSource(loadFile)
        d = decode(encode(a, pcm))
        pcm.WavSink(d, saveFile)

    # Encode to a file
    if opt.encode:
        a = pcm.WavSource(loadFile)
        (ar, g, pitch, hnr) = encode(a, pcm)

        # The cepstrum part is just like HTK
        c = ARCepstrum(ar, g, lpOrder[r])
        period = float(framePeriod)/r
        HTKSink(saveFile, c, period)

        # F0 and HNR are both text formats
        (path, ext) = splitext(saveFile)
        saveFileLF0 = path + ".f0"
        saveFileHNR = path + ".hnr"
        np.savetxt(saveFileLF0, np.log(pitch))
        np.savetxt(saveFileHNR, hnr)

    # Encode cont. pitch only to a file
    if opt.pitch:
        a = pcm.WavSource(loadFile)
        (ar, g, pitch, hnr) = encode(a, pcm)

        # F0 and HNR are both text formats
        np.savetxt(saveFile, pitch)

    # Decode from a file
    if opt.decode:
        (path, ext) = splitext(loadFile)
        loadFileLF0 = path + ".f0"
        loadFileHNR = path + ".hnr"
        pitch = np.exp(np.loadtxt(loadFileLF0))
        hnr = np.loadtxt(loadFileHNR)
        c, period = HTKSource(loadFile)
        (ar, g) = ARCepstrumToPoly(c)
        d = decode((ar, g, pitch, hnr))
        pcm.WavSink(d, saveFile)