import React from 'react';
import { motion } from 'framer-motion';
import { usePlayerStore } from '../store/usePlayerStore';

export const ControlsBar: React.FC = () => {
  const {
    isPlaying,
    setPlaying,
    prevTrack,
    nextTrack,
    currentTime,
    setCurrentTime,
    duration,
    volume,
    setVolume
  } = usePlayerStore();

  return (
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
  );
};
