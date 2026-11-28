"""Listening-oriented titles grounded in the rendered track, not source IDs."""

VERSION = 'experience-titles-1'


def title_for(report, rng):
    f = report['mix_features']; events = report['events']; arc = report.get('process')
    # Descriptions refer to measured sound and actual form; never invent a place,
    # field-recording provenance, named instrument, mood diagnosis or prior work.
    if f['flux'] > .18:
        subject = 'Small Pulses'
    elif f['flatness'] > .3:
        subject = 'Grains of Sound'
    elif f['centroid'] > .16:
        subject = 'Bright Traces'
    elif f['side_ratio'] > .42:
        subject = 'Wide Textures'
    else:
        subject = 'Soft Tones'
    endings = {
        'conversation-and-return': ['Meet, Separate, and Meet Again', 'Answer Each Other Across the Quiet'],
        'gathering-and-release': ['Gather Slowly and Fall Away', 'Open Into a Wider Space'],
        'crossing-perspectives': ['Cross Paths and Find Their Way Back', 'Move Between Near and Far'],
    }
    end = str(rng.choice(endings.get(arc, ['Leave a Trace in the Quiet'])))
    title = subject+' '+end
    report['title_basis'] = {'version': VERSION, 'subject': subject, 'arc': arc,
        'rendered_features': {k:f[k] for k in ('flux','flatness','centroid','side_ratio')},
        'returns': sum(e.get('action')=='return' for e in events),
        'meaning':'An editorial description of the measured sound and saved form, not a learned interpretation.'}
    return title
