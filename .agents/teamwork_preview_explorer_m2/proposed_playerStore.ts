import { create } from 'zustand';
import { Track } from '../api/mockApi';

export type ThemeName = string;

export interface PlayerState {
  isTransparencyEnabled: boolean;
  theme: ThemeName;
  currentTrack: Track | null;
  isPlaying: boolean;
  volume: number; // 0-100
  currentTime: number;
  duration: number;
  
  setTransparencyEnabled: (val: boolean) => void;
  setTheme: (theme: ThemeName) => void;
  setPlaying: (val: boolean) => void;
  setCurrentTrack: (track: Track | null) => void;
  setVolume: (vol: number) => void;
  setCurrentTime: (time: number) => void;
  nextTrack: () => void;
  prevTrack: () => void;
}

const STATIC_PLAYLIST: Track[] = [
  {
    id: '1',
    title: 'Aura of Light',
    artist: 'Lumina',
    album: 'Ethereal Vibes',
    duration: 180,
    coverUrl: 'https://example.com/cover1.jpg',
    audioUrl: 'https://example.com/audio1.mp3'
  },
  {
    id: '2',
    title: 'Neon Dreams',
    artist: 'Synthwave Kid',
    album: 'Retro Wave',
    duration: 210,
    coverUrl: 'https://example.com/cover2.jpg',
    audioUrl: 'https://example.com/audio2.mp3'
  },
  {
    id: '3',
    title: 'Ocean Breeze',
    artist: 'Nature Echoes',
    album: 'Relaxation',
    duration: 240,
    coverUrl: 'https://example.com/cover3.jpg',
    audioUrl: 'https://example.com/audio3.mp3'
  }
];

export const usePlayerStore = create<PlayerState>((set, get) => ({
  isTransparencyEnabled: false,
  theme: 'aura-dark',
  currentTrack: null,
  isPlaying: false,
  volume: 50,
  currentTime: 0,
  duration: 0,

  setTransparencyEnabled: (val) => set({ isTransparencyEnabled: !!val }),
  setTheme: (theme) => set({ theme }),
  setPlaying: (val) => set({ isPlaying: !!val }),
  setCurrentTrack: (track) => set({
    currentTrack: track,
    duration: track ? track.duration : 0,
    currentTime: 0
  }),
  setVolume: (vol) => set({ volume: Math.max(0, Math.min(100, vol)) }),
  setCurrentTime: (time) => set({ currentTime: time }),
  nextTrack: () => {
    const { currentTrack } = get();
    if (!currentTrack) {
      set({ currentTime: 0 });
      return;
    }
    const idx = STATIC_PLAYLIST.findIndex(t => t.id === currentTrack.id);
    if (idx === -1) {
      set({ currentTime: 0 });
      return;
    }
    const nextIdx = (idx + 1) % STATIC_PLAYLIST.length;
    const track = STATIC_PLAYLIST[nextIdx];
    set({
      currentTrack: track,
      duration: track.duration,
      currentTime: 0
    });
  },
  prevTrack: () => {
    const { currentTrack } = get();
    if (!currentTrack) {
      set({ currentTime: 0 });
      return;
    }
    const idx = STATIC_PLAYLIST.findIndex(t => t.id === currentTrack.id);
    if (idx === -1) {
      set({ currentTime: 0 });
      return;
    }
    const prevIdx = (idx - 1 + STATIC_PLAYLIST.length) % STATIC_PLAYLIST.length;
    const track = STATIC_PLAYLIST[prevIdx];
    set({
      currentTrack: track,
      duration: track.duration,
      currentTime: 0
    });
  },
}));
