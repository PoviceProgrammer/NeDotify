import React, { useEffect, useState } from 'react';
import { usePlayerStore } from '../store/usePlayerStore';
import { getTracks, Track } from '../api/mockApi';
import { motion, AnimatePresence } from 'framer-motion';

export const AurePlayer: React.FC = () => {
  const {
    isTransparencyEnabled,
    setTransparencyEnabled,
    theme,
    setTheme,
    currentTrack,
    isPlaying,
    setPlaying,
    volume,
    setVolume,
    currentTime,
    setCurrentTime,
    duration,
    nextTrack,
    prevTrack,
    setCurrentTrack
  } = usePlayerStore();

  const [tracks, setTracks] = useState<Track[]>([]);
  const [platform, setPlatform] = useState<'macos' | 'windows' | 'other'>('other');

  // Load tracks list from mock API layer
  useEffect(() => {
    getTracks().then((data) => {
      setTracks(data);
    });

    // Detect platform for styling spacing & padding (macOS Title Bar Offset)
    const userAgent = window.navigator.userAgent.toLowerCase();
    if (userAgent.includes('mac')) {
      setPlatform('macos');
    } else if (userAgent.includes('win')) {
      setPlatform('windows');
    }
  }, []);

  const themes = [
    'aura-dark', 'aura-light', 'neon-purple', 'cyberpunk', 'glass-morph',
    'sunset-glow', 'ocean-breeze', 'forest-mist', 'royal-gold', 'crimson-tide',
    'monochrome', 'matrix-green', 'pastel-pink', 'solar-flare', 'deep-space',
    'nordic-frost', 'vintage-sepia'
  ];

  return (
    <div
      className={`aure-player ${theme} ${isTransparencyEnabled ? 'translucent' : 'solid'} platform-${platform}`}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100%',
        backgroundColor: 'var(--bg-color)',
        color: 'var(--text-color)',
        transition: 'all 0.3s ease'
      }}
    >
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Sidebar Panel */}
        <aside
          data-testid="sidebar"
          className="no-scrollbar"
          style={{
            width: '260px',
            borderRight: '1px solid rgba(255, 255, 255, 0.1)',
            padding: '1.5rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '1.5rem',
            backgroundColor: 'var(--sidebar-bg)',
            overflowY: 'auto',
            transition: 'all 0.3s ease'
          }}
        >
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '0.75rem' }}>Navigation</h3>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <li style={{ cursor: 'pointer', padding: '0.25rem 0' }}>Home</li>
              <li style={{ cursor: 'pointer', padding: '0.25rem 0' }}>Library</li>
              <li style={{ cursor: 'pointer', padding: '0.25rem 0' }}>Playlists</li>
            </ul>
          </div>

          <div>
            <h4 style={{ fontSize: '0.95rem', fontWeight: 'bold', marginBottom: '0.75rem' }}>Theme Swatches</h4>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '0.4rem' }}>
              {themes.map((t) => (
                <button
                  key={t}
                  data-testid={`theme-swatch-${t}`}
                  onClick={() => setTheme(t)}
                  style={{
                    padding: '0.35rem 0.5rem',
                    border: '1px solid rgba(255, 255, 255, 0.15)',
                    background: theme === t ? 'var(--accent-color)' : 'rgba(255, 255, 255, 0.05)',
                    color: theme === t ? '#fff' : 'var(--text-color)',
                    cursor: 'pointer',
                    borderRadius: '6px',
                    fontSize: '0.7rem',
                    textAlign: 'center',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    transition: 'all 0.2s ease'
                  }}
                >
                  {t.replace('-', ' ')}
                </button>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 'auto', borderTop: '1px solid rgba(255, 255, 255, 0.1)', paddingTop: '1rem' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.85rem' }}>
              <input
                type="checkbox"
                data-testid="transparency-toggle"
                checked={!!isTransparencyEnabled}
                onChange={(e) => setTransparencyEnabled(e.target.checked)}
                style={{ cursor: 'pointer' }}
              />
              Enable Transparency
            </label>
          </div>
        </aside>

        {/* Main Content Area */}
        <main style={{ flex: 1, padding: '2rem', display: 'flex', flexDirection: 'column', overflowY: 'auto' }}>
          <header style={{ display: 'flex', justifyContent: 'between', alignItems: 'center', marginBottom: '2rem' }}>
            <h2 style={{ fontSize: '1.75rem', fontWeight: 'bold' }}>AURA Music Player</h2>
          </header>

          <div style={{ display: 'flex', gap: '3rem', alignItems: 'center', flexWrap: 'wrap', flex: 1 }}>
            {/* Cover Art Container with Framer Motion transitions */}
            <motion.div
              data-testid="cover-art"
              style={{
                width: '320px',
                height: '320px',
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: '12px',
                overflow: 'hidden',
                boxShadow: isTransparencyEnabled ? '0 10px 30px rgba(0,0,0,0.3)' : 'none',
                position: 'relative'
              }}
              whileHover={{ scale: 1.02 }}
              transition={{ duration: 0.3 }}
            >
              <AnimatePresence mode="wait">
                {currentTrack ? (
                  <motion.img
                    key={currentTrack.id}
                    src={currentTrack.coverUrl}
                    alt={currentTrack.title}
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    transition={{ duration: 0.25 }}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                ) : (
                  <motion.div
                    key="no-track"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    style={{ fontSize: '1rem', opacity: 0.6 }}
                  >
                    No Track Loaded
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>

            {/* Track metadata details */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', minWidth: '250px' }}>
              <h3 style={{ fontSize: '2rem', fontWeight: 'bold', margin: 0 }}>
                {currentTrack ? currentTrack.title : 'No Track Playing'}
              </h3>
              <p style={{ fontSize: '1.2rem', opacity: 0.8, margin: 0 }}>
                {currentTrack ? currentTrack.artist : 'Unknown Artist'}
              </p>
              <p style={{ fontSize: '1rem', opacity: 0.5, margin: 0 }}>
                {currentTrack ? currentTrack.album : 'Unknown Album'}
              </p>
            </div>
          </div>

          {/* Interactive Playable Tracks List (Mock layer verification) */}
          <div style={{ marginTop: '2rem' }}>
            <h4 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem' }}>Tracks Queue</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {tracks.map((track) => {
                const isActive = currentTrack?.id === track.id;
                return (
                  <div
                    key={track.id}
                    onClick={() => {
                      setCurrentTrack(track);
                      setPlaying(true);
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.75rem 1rem',
                      backgroundColor: isActive ? 'rgba(255, 255, 255, 0.1)' : 'rgba(255, 255, 255, 0.02)',
                      borderRadius: '8px',
                      cursor: 'pointer',
                      borderLeft: isActive ? '4px solid var(--accent-color)' : '4px solid transparent',
                      transition: 'all 0.2s ease'
                    }}
                  >
                    <div>
                      <span style={{ fontWeight: isActive ? 'bold' : 'normal' }}>{track.title}</span>
                      <span style={{ fontSize: '0.85rem', opacity: 0.6, marginLeft: '1rem' }}>by {track.artist}</span>
                    </div>
                    <span style={{ fontSize: '0.85rem', opacity: 0.6 }}>{track.duration}s</span>
                  </div>
                );
              })}
            </div>
          </div>
        </main>
      </div>

      {/* Footer Controls Panel */}
      <footer
        role="contentinfo"
        style={{
          height: '100px',
          borderTop: '1px solid rgba(255, 255, 255, 0.1)',
          padding: '1rem 2rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          backgroundColor: 'var(--controls-bg)',
          transition: 'all 0.3s ease'
        }}
      >
        {/* Buttons Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <motion.button
            data-testid="prev-button"
            onClick={prevTrack}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
              color: 'var(--text-color)',
              cursor: 'pointer'
            }}
          >
            Prev
          </motion.button>
          <motion.button
            data-testid="play-pause-button"
            onClick={() => setPlaying(!isPlaying)}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            style={{
              padding: '0.5rem 1.5rem',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: 'var(--accent-color)',
              color: '#fff',
              fontWeight: 'bold',
              cursor: 'pointer'
            }}
          >
            {isPlaying ? 'Pause' : 'Play'}
          </motion.button>
          <motion.button
            data-testid="next-button"
            onClick={nextTrack}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: 'rgba(255, 255, 255, 0.05)',
              color: 'var(--text-color)',
              cursor: 'pointer'
            }}
          >
            Next
          </motion.button>
        </div>

        {/* Progress scrub Slider */}
        <div style={{ flex: 1, margin: '0 3rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span style={{ fontSize: '0.85rem', opacity: 0.6 }}>{currentTime}s</span>
          <input
            type="range"
            data-testid="progress-slider"
            min={0}
            max={duration || 100}
            value={currentTime}
            onChange={(e) => setCurrentTime(Number(e.target.value))}
            style={{
              flex: 1,
              cursor: 'pointer',
              height: '4px',
              borderRadius: '2px',
              outline: 'none'
            }}
          />
          <span style={{ fontSize: '0.85rem', opacity: 0.6 }}>{duration}s</span>
        </div>

        {/* Volume scrub Slider */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ fontSize: '0.85rem', opacity: 0.6 }}>Vol</span>
          <input
            type="range"
            data-testid="volume-slider"
            min={0}
            max={100}
            value={volume}
            onChange={(e) => setVolume(Number(e.target.value))}
            style={{
              width: '100px',
              cursor: 'pointer',
              height: '4px',
              borderRadius: '2px',
              outline: 'none'
            }}
          />
          <span style={{ fontSize: '0.85rem', opacity: 0.8, width: '40px' }}>{volume}%</span>
        </div>
      </footer>
    </div>
  );
};
