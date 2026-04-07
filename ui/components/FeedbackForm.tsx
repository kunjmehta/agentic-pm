/**
 * FeedbackForm component - Plan rejection feedback form
 *
 * Allows users to reject a plan and provide structured feedback
 * for the PM agent to revise the approach.
 */

'use client';

import { useState } from 'react';

interface FeedbackFormProps {
  onSubmit: (feedbackText: string) => void;
  onCancel: () => void;
}

export function FeedbackForm({ onSubmit, onCancel }: FeedbackFormProps) {
  const [feedback, setFeedback] = useState('');

  const handleSubmit = () => {
    if (feedback.trim()) {
      onSubmit(feedback.trim());
    }
  };

  return (
    <div className="bg-gray-900 border border-amber-600 rounded p-4 space-y-4 mt-4">
      <h3 className="text-lg font-semibold text-amber-400 font-mono uppercase tracking-wide">
        Provide Feedback on Plan
      </h3>

      <div>
        <label className="block text-sm text-gray-300 mb-2 font-mono">
          What changes would you like to the plan?
        </label>
        <textarea
          className="w-full bg-gray-800 border border-gray-600 rounded px-3 py-2 text-white font-mono text-sm focus:outline-none focus:border-amber-500"
          rows={6}
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          placeholder="Example: The plan is too aggressive. Please use conservative position sizing (max 5% per trade) and focus on defensive stocks like utilities and consumer staples. Also add stop losses at 2%."
        />
        <p className="text-xs text-gray-500 mt-2 font-mono">
          Be specific about what you want changed. The PM agent will revise the plan based on your feedback.
        </p>
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleSubmit}
          disabled={!feedback.trim()}
          className="px-4 py-2 bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed font-mono text-sm uppercase tracking-wide transition-colors"
        >
          Send Feedback
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-600 font-mono text-sm uppercase tracking-wide transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
