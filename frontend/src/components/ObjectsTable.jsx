import { motion } from 'framer-motion';

const ObjectsTable = ({ objects }) => {
  if (!objects || Object.keys(objects).length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 50 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4 }}
      className="bg-white rounded-2xl shadow-xl overflow-hidden"
    >
      <div className="bg-gradient-to-r from-gray-700 to-gray-800 px-8 py-6">
        <h3 className="text-2xl font-bold text-white">Current Items Viewed</h3>
        <p className="text-gray-300 text-sm mt-1">Objects detected in your interior space</p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider w-12">
                #
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider w-1/4">
                Object
              </th>
              <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                Description
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {Object.entries(objects).map(([item, desc], index) => (
              <motion.tr
                key={item}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.5 + index * 0.05 }}
                className="hover:bg-gray-50 transition-colors"
              >
                <td className="px-6 py-4 text-sm text-gray-500 font-medium">{index + 1}</td>
                <td className="px-6 py-4">
                  <span className="text-base font-semibold text-gray-800 capitalize">{item}</span>
                </td>
                <td className="px-6 py-4 text-sm text-gray-700">{desc}</td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
};

export default ObjectsTable;
