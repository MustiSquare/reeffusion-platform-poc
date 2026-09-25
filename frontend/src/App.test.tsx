import '@testing-library/jest-dom/vitest';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { App } from './main';
vi.mock('./api/client',()=>({getJson:vi.fn(async()=>[]),postJson:vi.fn(),putJson:vi.fn(),deleteJson:vi.fn(),uploadFiles:vi.fn(),assetUrl:(url:string)=>url}));

describe('App theme toggle', () => {
  it('switches the document theme when the toggle is clicked and persists the choice', () => {
    window.localStorage.clear();
    render(<App />);

    const toggle = screen.getByRole('button', { name: /toggle theme/i });
    fireEvent.click(toggle);

    expect(document.documentElement.dataset.theme).toBe('light');
    expect(window.localStorage.getItem('reef-theme')).toBe('light');
    expect(screen.getByRole('button', { name: /toggle theme/i })).toHaveTextContent('Light mode');
  });
});
