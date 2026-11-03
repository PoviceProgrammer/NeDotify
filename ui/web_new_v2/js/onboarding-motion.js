// Motion stays inside the wizard; no timers or listeners survive its session.
export function mountOnboardingMotion(wizard, {signal}) {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const running = new Set();
    const beats = ['Твоё настроение', 'Твой темп', 'Твоё звучание', 'Твоя коллекция', 'Твои открытия', 'Твой NeDotify'];
    const icons = ['palette', 'sparkles', 'headphones', 'library', 'radio', 'check'];
    const steps = [...wizard.querySelectorAll('.onboarding-step')];
    wizard.querySelectorAll('[data-ob-motion]').forEach(node => node.remove());
    steps.forEach((step, index) => {
        const badge = document.createElement('div');
        badge.className = 'ob-step-beat';
        badge.dataset.obMotion = '';
        badge.setAttribute('aria-hidden', 'true');
        badge.innerHTML = `<span class="ob-beat-icon"><i data-lucide="${icons[index]}"></i></span><span>${beats[index]}</span><span class="ob-beat-number">0${index + 1} / 0${steps.length}</span>`;
        step.prepend(badge);
    });
    const waves = document.createElement('div');
    waves.className = 'ob-preview-waves';
    waves.dataset.obMotion = '';
    waves.setAttribute('aria-hidden', 'true');
    waves.innerHTML = '<i></i>'.repeat(9);
    wizard.querySelector('.ob-preview-cover').append(waves);
    const stage = document.createElement('div');
    stage.className = 'ob-visual-stage';
    stage.dataset.obMotion = '';
    stage.setAttribute('aria-hidden', 'true');
    stage.innerHTML = `<div class="ob-stage-orbit"></div><div class="ob-stage-orbit ob-stage-orbit-second"></div>
        <div class="ob-stage-theme"><span></span><span></span><span></span></div>
        <div class="ob-stage-audio">${'<span></span>'.repeat(15)}</div>
        <div class="ob-stage-library"><span><i data-lucide="music-2"></i></span><span><i data-lucide="disc-3"></i></span><span><i data-lucide="headphones"></i></span></div>
        <div class="ob-stage-sources"><span data-ob-stage-youtube>YouTube</span><span data-ob-stage-soundcloud>SoundCloud</span><span class="ob-stage-format">Оригинал</span></div>
        <div class="ob-stage-ready"><i data-lucide="check"></i></div>`;
    wizard.querySelector('.ob-preview-cover').append(stage);
    const caption = document.createElement('div');
    caption.className = 'ob-scene-caption';caption.dataset.obMotion = '';
    caption.innerHTML = '<span class="ob-scene-eyebrow">ПРЕДПРОСМОТР</span><strong></strong><p></p>';
    wizard.querySelector('.ob-player-preview').after(caption);
    const progressTrack = document.createElement('div');
    progressTrack.className = 'ob-progress-track';progressTrack.dataset.obMotion = '';
    progressTrack.setAttribute('aria-hidden','true');progressTrack.innerHTML = '<span></span>';
    wizard.querySelector('#ob-progress').before(progressTrack);
    const sceneCopy = [
        ['Твоя музыка. Твой характер.', 'Цвет и оформление меняются вместе с выбором.'],
        ['Движение в твоём ритме', 'Выбери подходящий режим визуальных эффектов.'],
        ['Всё начинается со звука', 'Устройство, переходы и громкость — под твои наушники.'],
        ['Любимое уже рядом', 'Перенеси плейлист или собери коллекцию с первого трека.'],
        ['Открывай больше музыки', 'Выбери площадки поиска и формат для сохранения.'],
        ['Можно начинать', 'Твои настройки готовы. Впереди — музыка.'],
    ];

    function cancel() {
        for (const animation of running) animation.cancel();
        running.clear();
    }
    function animate(node, frames, options = {}) {
        if (!node?.animate || reduced.matches || signal.aborted) return null;
        const animation = node.animate(frames, {duration: 460, easing: 'cubic-bezier(.22,1,.36,1)', ...options});
        running.add(animation);
        animation.finished.then(() => { running.delete(animation);animation.cancel(); }, () => running.delete(animation));
        return animation;
    }
    signal.addEventListener('abort', cancel, {once: true});
    const visibility = () => { wizard.dataset.documentHidden = String(document.hidden); };
    document.addEventListener('visibilitychange', visibility, {signal});
    visibility();
    reduced.addEventListener('change', cancel, {signal});
    wizard.addEventListener('click', event => {
        const choice = event.target.closest('[data-ob-theme],[data-ob-profile],[data-ob-library],[data-ob-style]');
        if (choice && !choice.disabled) animate(choice, [
            {transform: 'scale(.97)'}, {transform: 'scale(1.025)', offset: .55}, {transform: 'scale(1)'}
        ], {duration: 340});
    }, {signal});
    return {
        preview(draft) {
            wizard.dataset.previewStyle = draft.uiStyle || 'current';
            wizard.dataset.previewCrossfade = String(Boolean(draft.crossfade));
            stage.querySelector('[data-ob-stage-youtube]').classList.toggle('is-off', draft.sources?.youtube === false);
            stage.querySelector('[data-ob-stage-soundcloud]').classList.toggle('is-off', draft.sources?.soundcloud === false);
            stage.querySelector('.ob-stage-format').textContent = draft.format === 'source' ? 'Оригинал' : String(draft.format || 'Оригинал').toUpperCase();
        },
        enter() {
            animate(wizard.querySelector('.ob-shell'), [{opacity: 0, transform: 'translateY(24px) scale(.97)'}, {opacity: 1, transform: 'none'}], {duration: 650});
            animate(wizard.querySelector('.ob-player-preview'), [{opacity: 0, transform: 'translateY(28px) rotate(-3deg)'}, {opacity: 1, transform: 'none'}], {delay: 100, duration: 750, fill: 'backwards'});
        },
        step(number, previous) {
            cancel();
            wizard.dataset.motionStep = String(number);
            const copy = sceneCopy[number - 1];
            caption.querySelector('strong').textContent = copy[0];
            caption.querySelector('p').textContent = copy[1];
            animate(caption, [{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'none'}]);
            animate(stage, [{opacity: .35, transform: `translateX(${number >= previous ? 18 : -18}px) scale(.92)`}, {opacity:1,transform:'none'}], {duration:650});
            const direction = number >= previous ? 1 : -1;
            // Animate the actual form nodes. No clones, duplicate ids or delayed navigation.
            const step = steps[number - 1];
            const nodes = step.querySelectorAll(':scope > .ob-step-beat,:scope > h2,:scope > .ob-lead,.ob-fieldset,.ob-option,.ob-library-choice,.ob-summary > div,.ob-tip');
            nodes.forEach((node, index) => animate(node, [
                {opacity: 0, transform: `translate(${direction * 22}px, 12px)`},
                {opacity: 1, transform: 'none'}
            ], {delay: Math.min(index * 38, 220), fill: 'backwards', duration: 480}));
            const active = wizard.querySelector('[aria-current="step"] > span');
            animate(active, [{transform: 'scale(.8)'}, {transform: 'scale(1.15)', offset: .6}, {transform: 'scale(1)'}]);
        },
        async complete() {
            cancel();
            wizard.dataset.motionState = 'complete';
            const animation = animate(wizard.querySelector('.ob-shell'), [
                {opacity: 1, transform: 'none'}, {opacity: 0, transform: 'translateY(-12px) scale(1.025)'}
            ], {duration: 320, fill: 'forwards'});
            if (animation) await animation.finished.catch(() => {});
        },
    };
}
