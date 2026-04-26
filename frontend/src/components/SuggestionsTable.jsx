import { motion } from 'framer-motion';

const SuggestionsTable = ({ objects, editSuggestions, polishedPrompts }) => {
  const detectedObjects = objects || {};
  const suggestions = editSuggestions || {};
  const polished = polishedPrompts || {};

  // Render rows in detection order. Each row pairs the VLM draft with the
  // chatbot's enriched version; when the chatbot didn't polish a specific
  // object we fall back to the VLM draft in the chatbot column so the row
  // never shows empty.
  const matchedSuggestions = Object.keys(detectedObjects)
    .filter((objName) => suggestions[objName])
    .map((objName) => [
      objName,
      suggestions[objName],
      polished[objName] || suggestions[objName],
      Boolean(polished[objName]),
    ]);

  if (matchedSuggestions.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.6 }}
      className="bg-white rounded-2xl shadow-xl overflow-hidden"
    >
      <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-8 py-6">
        <h3 className="text-2xl font-bold text-white">Suggested Edits</h3>
        <p className="text-indigo-100 text-sm mt-1">
          VLM first-pass draft on the left; the fine-tuned designer chatbot&rsquo;s refinement on the right. Rows without chatbot polish fall back to the VLM suggestion.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-indigo-50 border-b border-indigo-100">
            <tr>
              <th className="px-6 py-4 text-left text-xs font-semibold text-indigo-700 uppercase tracking-wider w-12">
                #
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-indigo-700 uppercase tracking-wider w-1/6">
                Object
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-indigo-700 uppercase tracking-wider w-2/5">
                VLM Suggestion
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-indigo-700 uppercase tracking-wider w-2/5">
                Chatbot Suggestion
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {matchedSuggestions.map(([item, draft, refinement, hasPolish], index) => (
              <motion.tr
                key={item}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.7 + index * 0.05 }}
                className="hover:bg-indigo-50/30 transition-colors align-top"
              >
                <td className="px-6 py-4 text-sm text-gray-500 font-medium">{index + 1}</td>
                <td className="px-6 py-4">
                  <span className="text-base font-semibold text-indigo-700 capitalize">{item}</span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-600 font-normal">{draft}</td>
                <td className="px-6 py-4 text-sm">
                  {hasPolish ? (
                    <span className="text-gray-800 font-medium">{refinement}</span>
                  ) : (
                    <span
                      className="text-gray-500 italic"
                      title="Chatbot did not polish this object; falling back to VLM suggestion"
                    >
                      {refinement}
                    </span>
                  )}
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
};

export default SuggestionsTable;
