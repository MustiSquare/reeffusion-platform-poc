import React from 'react';
import {afterEach,expect,it} from 'vitest';
import {render,screen,cleanup} from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import SurveyTiming,{surveyTiming} from './SurveyTiming';
afterEach(cleanup);
it('marks the date and exact fractional hours rather than the entire hour',()=>{
  const survey={started_at:'2026-08-21T20:15:00Z',ended_at:'2026-08-21T20:56:00Z'};
  const value=surveyTiming(survey)!;
  expect(value.days).toHaveLength(14);
  expect(value.hours).toBe(24);expect(value.days.filter(d=>d.active)).toHaveLength(1);
  expect(value.left).toBeCloseTo(20.25/24*100);
  expect(value.width).toBeCloseTo(41/1440*100);
  const {container}=render(<SurveyTiming survey={survey}/>);
  expect(container.querySelectorAll('.archive-date.is-recorded')).toHaveLength(1);
  expect(screen.getByText('24 hours')).toBeInTheDocument();
  expect(screen.getByText('August 2026')).toBeInTheDocument();
  expect(container.querySelectorAll('.archive-date')).toHaveLength(14);
});
it('expands overnight recordings across month/year boundaries and uses UTC',()=>{
  const value=surveyTiming({started_at:'2026-12-31T23:10:00Z',ended_at:'2027-01-01T01:25:00Z'})!;
  expect(value.hours).toBe(48);expect(value.days.filter(d=>d.active)).toHaveLength(2);
  expect(value.width).toBeCloseTo(2.25/48*100);
  const offset=surveyTiming({started_at:'2027-01-01T01:10:00+02:00',duration_seconds:8100})!;
  expect(offset.start).toBe(value.start);expect(offset.end).toBe(value.end);
});
it('does not highlight the following date when the recording ends exactly at midnight',()=>{
  const value=surveyTiming({started_at:'2026-08-21T23:00:00Z',ended_at:'2026-08-22T00:00:00Z'})!;
  expect(value.hours).toBe(24);expect(value.days.filter(d=>d.active)).toHaveLength(1);
  expect(value.left+value.width).toBeCloseTo(100);
});
it('does not invent a duration for missing or invalid metadata',()=>{
  expect(surveyTiming({})).toBeNull();
  const survey={started_at:'2026-08-21T20:00:00Z',ended_at:'bad'};
  expect(surveyTiming(survey)!.end).toBeNull();
  const {container}=render(<SurveyTiming survey={survey}/>);
  expect(screen.getByText('End time unavailable')).toBeInTheDocument();
  expect(container.querySelector('.archive-hours-recorded')).toBeNull();
});

it('labels both months and years when the fortnight crosses a year boundary',()=>{
  render(<SurveyTiming survey={{started_at:'2026-12-31T23:10:00Z',ended_at:'2027-01-01T01:25:00Z'}}/>);
  expect(screen.getByText('December 2026 \u2013 January 2027')).toBeInTheDocument();
});
