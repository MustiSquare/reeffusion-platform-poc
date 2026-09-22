// @vitest-environment jsdom
import React from 'react';
import { afterEach, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import ConditionsSprites, { seaPath } from './ConditionsSprites';
afterEach(cleanup);
it('updates downwind bearing and wave graphic when hourly values change',()=>{
  const {rerender}=render(<ConditionsSprites windFrom={0} windSpeed={10} waveHeight={0}/>);
  expect(screen.getByTestId('windsock-bearing')).toHaveAttribute('transform','rotate(90 32 32)');
  expect(screen.getByText('From N')).toBeInTheDocument();
  expect(screen.getByText('Calm sea')).toBeInTheDocument();
  const flat=screen.getByRole('img',{name:'Significant wave height 0.00 metres'}).querySelectorAll('path')[1].getAttribute('d');
  rerender(<ConditionsSprites windFrom={90} windSpeed={22} waveHeight={3}/>);
  expect(screen.getByTestId('windsock-bearing')).toHaveAttribute('transform','rotate(180 32 32)');
  expect(screen.getByText('From E')).toBeInTheDocument();
  expect(screen.getByText('22.0 km/h')).toBeInTheDocument();
  expect(screen.getByRole('img',{name:'Significant wave height 3.00 metres'}).querySelectorAll('path')[1].getAttribute('d')).not.toBe(flat);
});
it('distinguishes calm wind from absent data and does not invent calm seas',()=>{
  const {rerender}=render(<ConditionsSprites windFrom={null} windSpeed={null} waveHeight={null}/>);
  expect(screen.getByRole('img',{name:'Wind unavailable'})).toBeInTheDocument();
  expect(screen.getByRole('img',{name:'Sea state unavailable'})).toBeInTheDocument();
  expect(screen.queryByTestId('windsock-bearing')).not.toBeInTheDocument();
  rerender(<ConditionsSprites windFrom={180} windSpeed={0} waveHeight={0}/>);
  expect(screen.getByRole('img',{name:'Calm wind'})).toBeInTheDocument();
  expect(screen.queryByTestId('windsock-bearing')).not.toBeInTheDocument();
});
it('increases wave amplitude while keeping extreme waves inside the sprite',()=>{
  const span=(h:number)=>{const ys=[...seaPath(h).matchAll(/,([\d.-]+)/g)].map(m=>Number(m[1]));return Math.max(...ys)-Math.min(...ys);};
  expect(span(0)).toBe(0);
  expect(span(.2)).toBeLessThan(span(1));
  expect(span(1)).toBeLessThan(span(4));
  expect(span(100)).toBeLessThanOrEqual(38);
});
