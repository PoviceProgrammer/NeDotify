import React, { useEffect, useState } from 'react';
import { usePlayerStore } from '../store/usePlayerStore';
import { getTracks, Track } from '../api/mockApi';
import { Sidebar } from './Sidebar';
import { MainPanel } from './MainPanel';
import { ControlsBar } from './ControlsBar';

export const AurePlayer: React.FC = () => {
  const {
    isTransparencyEnabled,
    theme
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
        <Sidebar />
        <MainPanel tracks={tracks} />
      </div>
      <ControlsBar />
    </div>
  );
};
