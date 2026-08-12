import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { usePlayerStore } from '../store/usePlayerStore';
import { Track } from '../api/mockApi';

export interface MainPanelProps {
  tracks: Track[];
}

export const MainPanel: React.FC<MainPanelProps> = ({ tracks }) => {
  const {
    currentTrack,
    setCurrentTrack,
    setPlaying,
    isTransparencyEnabled
  } = usePlayerStore();

  return (
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

      {/* Interactive Playable Tracks List */}
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
  );
};
