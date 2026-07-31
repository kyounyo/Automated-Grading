import React, { createContext, useState, useContext } from 'react';

const mockDatasets = {
  'nlp101-q1': {
    title: 'NLP101 - Text Processing Quiz',
    metrics: { total: 170, autoApproved: 152, actionRequired: 18, randomAudit: '5%' },
    chartData: [
      { range: '0-49', count: 5 }, { range: '50-59', count: 12 }, { range: '60-69', count: 45 },
      { range: '70-79', count: 68 }, { range: '80-89', count: 32 }, { range: '90-100', count: 8 },
    ],
    students: [
      { 
        id: '32918824', name: 'Student 1', submittedAt: 'Oct 12, 14:32', score: 100, status: 'auto-approved',
        evaluations: [
          { qId: 'q1', question: 'Q1. What is the difference between a word token and a word type?', studentText: 'A word token refers to a single occurrence of a word in a text. A word type represents the unique form of a word, irrespective of its occurrences in a text.', aiScore: '20 / 20', aiJustification: 'Perfect definition matching the rubric.', highlightText: 'single occurrence of a word in a text', status: 'auto-approved' },
          { qId: 'q2', question: 'Q2. How can we interpret the most frequent words in a text?', studentText: 'The most frequent words are often functional words (e.g., the, and) that provide grammatical structure but carry limited semantic meaning.', aiScore: '20 / 20', aiJustification: 'Accurately identified functional words.', highlightText: 'functional words', status: 'auto-approved' },
          { qId: 'q3', question: 'Q3. What is the difference between a word and a token?', studentText: 'A word is a linguistic unit of meaning. A token is any individual unit into which text can be divided, like subwords or punctuation.', aiScore: '20 / 20', aiJustification: 'Correctly distinguished linguistic unit vs text division unit.', highlightText: 'any individual unit into which text can be divided', status: 'auto-approved' },
          { qId: 'q4', question: 'Q4. What types of tokens should not be split by punctuation delimiters?', studentText: 'URLs, email addresses, decimal numbers, and abbreviations should not be split.', aiScore: '20 / 20', aiJustification: 'Listed all required examples.', highlightText: 'URLs, email addresses, decimal numbers', status: 'auto-approved' },
          { qId: 'q5', question: 'Q5. What would be a scalable approach to handling diverse tokenizer cases?', studentText: 'Using regular expressions or a byte-pair encoder is a more scalable approach.', aiScore: '20 / 20', aiJustification: 'Correctly identified regex and BPE.', highlightText: 'byte-pair encoder', status: 'auto-approved' }
        ]
      },
      { 
        id: '32918825', name: 'Student 2', submittedAt: 'Oct 12, 14:45', score: 49, status: 'action-required', flagReason: 'Borderline Grade (49%)',
        evaluations: [
          { qId: 'q1', question: 'Q1. What is the difference between a word token and a word type?', studentText: 'A word token is just a word in a sentence, and a word type is any unique part of speech.', aiScore: '5 / 20', aiJustification: 'Confused word type with parts of speech.', highlightText: 'unique part of speech', status: 'action-required', flagReason: 'Borderline check: Review requested.' },
          { qId: 'q2', question: 'Q2. How can we interpret the most frequent words in a text?', studentText: 'The most frequent words are the most important ones because they are used the most in a text.', aiScore: '4 / 20', aiJustification: 'Incorrect. Frequent words are often functional, not semantically important.', highlightText: 'most important ones', status: 'auto-approved' },
          { qId: 'q3', question: 'Q3. What is the difference between a word and a token?', studentText: 'A word is a linguistic unit of meaning in natural language that usually corresponds to standalone words. Token is a unit of text used by an NLP model after tokenization.', aiScore: '20 / 20', aiJustification: 'Acceptable definition.', highlightText: 'unit of text used by an NLP model', status: 'auto-approved' },
          { qId: 'q4', question: 'Q4. What types of tokens should not be split by punctuation delimiters?', studentText: 'Proper nouns, email, and decimal numbers should not be split by punctuation-based tokenization.', aiScore: '15 / 20', aiJustification: 'Missed URLs and abbreviations.', highlightText: 'Proper nouns', status: 'auto-approved' },
          { qId: 'q5', question: 'Q5. What would be a scalable approach to handling diverse tokenizer cases?', studentText: 'Regular expressions.', aiScore: '5 / 20', aiJustification: 'Vague, missed BPE.', highlightText: 'Regular expressions', status: 'auto-approved' }
        ]
      },
      { 
        id: '32918826', name: 'Student 3', submittedAt: 'Oct 12, 15:01', score: 72, status: 'action-required', flagReason: 'Auditor Conflict (Q4)',
        evaluations: [
          { qId: 'q1', question: 'Q1. What is the difference between a word token and a word type?', studentText: 'Token is occurrence, type is the unique word.', aiScore: '15 / 20', aiJustification: 'Correct but lacks detail.', highlightText: 'Token is occurrence', status: 'auto-approved' },
          { qId: 'q2', question: 'Q2. How can we interpret the most frequent words in a text?', studentText: 'They are usually stop words like "the".', aiScore: '15 / 20', aiJustification: 'Correctly identified stop words.', highlightText: 'stop words', status: 'auto-approved' },
          { qId: 'q3', question: 'Q3. What is the difference between a word and a token?', studentText: 'Words have meaning, tokens are just splits.', aiScore: '12 / 20', aiJustification: 'A bit too informal.', highlightText: 'just splits', status: 'auto-approved' },
          { qId: 'q4', question: 'Q4. What types of tokens should not be split by punctuation delimiters?', studentText: 'Names like O\'Connor and words with hyphens.', aiScore: '10 / 20', aiJustification: 'Gave examples instead of categories (URLs, emails).', highlightText: 'words with hyphens', status: 'action-required', flagReason: 'Auditor Note: Grader gave 10/20, but rubric requires 0 points if specific categories (email/URL) are missing. Review recommended.' },
          { qId: 'q5', question: 'Q5. What would be a scalable approach to handling diverse tokenizer cases?', studentText: 'Data-driven BPE.', aiScore: '20 / 20', aiJustification: 'Accurate.', highlightText: 'Data-driven BPE', status: 'auto-approved' }
        ]
      },
      { 
        id: '32918827', name: 'Student 4', submittedAt: 'Oct 12, 15:15', score: 90, status: 'action-required', flagReason: 'Random Audit (5%)',
        evaluations: [
          { qId: 'q1', question: 'Q1. What is the difference between a word token and a word type?', studentText: 'Token = instance. Type = vocabulary entry.', aiScore: '20 / 20', aiJustification: 'Perfect concise definition.', highlightText: 'vocabulary entry', status: 'auto-approved' },
          { qId: 'q2', question: 'Q2. How can we interpret the most frequent words in a text?', studentText: 'Mostly functional words with low semantics.', aiScore: '20 / 20', aiJustification: 'Accurate.', highlightText: 'Mostly functional words', status: 'auto-approved' },
          { qId: 'q3', question: 'Q3. What is the difference between a word and a token?', studentText: 'Word has meaning, token is arbitrary split.', aiScore: '15 / 20', aiJustification: 'Accurate.', highlightText: 'arbitrary split', status: 'auto-approved' },
          { qId: 'q4', question: 'Q4. What types of tokens should not be split by punctuation delimiters?', studentText: 'Emails, URLs, decimals.', aiScore: '20 / 20', aiJustification: 'Accurate.', highlightText: 'Emails, URLs, decimals', status: 'action-required', flagReason: 'Random Audit: Selected for QA.' },
          { qId: 'q5', question: 'Q5. What would be a scalable approach to handling diverse tokenizer cases?', studentText: 'Regex or BPE models.', aiScore: '15 / 20', aiJustification: 'Accurate.', highlightText: 'BPE models', status: 'auto-approved' }
        ]
      },
      { 
        id: '32918828', name: 'Student 5', submittedAt: 'Oct 12, 15:30', score: 62, status: 'action-required', flagReason: 'Low Confidence (62%)',
        evaluations: [
          { qId: 'q1', question: 'Q1. What is the difference between a word token and a word type?', studentText: 'One is a token and one is a type.', aiScore: '0 / 20', aiJustification: 'Tautology.', highlightText: 'One is a token', status: 'action-required', flagReason: 'Grader Confidence: 62%. Ambiguous phrasing.' },
          { qId: 'q2', question: 'Q2. How can we interpret the most frequent words in a text?', studentText: 'They are very common.', aiScore: '5 / 20', aiJustification: 'Vague.', highlightText: 'very common', status: 'auto-approved' },
          { qId: 'q3', question: 'Q3. What is the difference between a word and a token?', studentText: 'Tokens are used in LLMs.', aiScore: '10 / 20', aiJustification: 'Technically true but misses definition.', highlightText: 'used in LLMs', status: 'auto-approved' },
          { qId: 'q4', question: 'Q4. What types of tokens should not be split by punctuation delimiters?', studentText: 'Things that need punctuation.', aiScore: '0 / 20', aiJustification: 'Incorrect.', highlightText: 'need punctuation', status: 'auto-approved' },
          { qId: 'q5', question: 'Q5. What would be a scalable approach to handling diverse tokenizer cases?', studentText: 'A better algorithm.', aiScore: '0 / 20', aiJustification: 'Vague.', highlightText: 'better algorithm', status: 'auto-approved' }
        ]
      },
      { 
        id: '32918829', name: 'Student 6', submittedAt: 'Oct 12, 15:45', score: 85, status: 'auto-approved',
        evaluations: [
          { qId: 'q1', question: 'Q1. What is the difference between a word token and a word type?', studentText: 'Tokens are occurrences, types are unique representations.', aiScore: '20 / 20', aiJustification: 'Clear and correct.', highlightText: 'types are unique representations', status: 'auto-approved' },
          { qId: 'q2', question: 'Q2. How can we interpret the most frequent words in a text?', studentText: 'They are stop words.', aiScore: '15 / 20', aiJustification: 'Clear and correct.', highlightText: 'stop words', status: 'auto-approved' },
          { qId: 'q3', question: 'Q3. What is the difference between a word and a token?', studentText: 'Words are linguistic, tokens are computational.', aiScore: '20 / 20', aiJustification: 'Excellent distinction.', highlightText: 'computational', status: 'auto-approved' },
          { qId: 'q4', question: 'Q4. What types of tokens should not be split by punctuation delimiters?', studentText: 'Emails, IP addresses.', aiScore: '15 / 20', aiJustification: 'Missed URLs.', highlightText: 'IP addresses', status: 'auto-approved' },
          { qId: 'q5', question: 'Q5. What would be a scalable approach to handling diverse tokenizer cases?', studentText: 'Byte Pair Encoding.', aiScore: '15 / 20', aiJustification: 'Correct.', highlightText: 'Byte Pair Encoding', status: 'auto-approved' }
        ]
      }
    ]
  }
};

export const AssignmentContext = createContext();

export const AssignmentProvider = ({ children }) => {
  const [currentAssignmentId, setCurrentAssignmentId] = useState('nlp101-q1');

  const currentData = mockDatasets[currentAssignmentId] || mockDatasets['nlp101-q1'];

  const availableAssignments = Object.keys(mockDatasets).map(id => ({
    id,
    title: mockDatasets[id].title
  }));

  return (
    <AssignmentContext.Provider value={{ currentAssignmentId, setCurrentAssignmentId, currentData, availableAssignments }}>
      {children}
    </AssignmentContext.Provider>
  );
};

export const useAssignment = () => useContext(AssignmentContext);
