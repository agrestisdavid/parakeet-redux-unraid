// Small adapter for the pinned parakeet.cpp internal thread-setting API.
// The upstream C API's single-backend mode does not apply threads_each.
namespace pk { void set_num_threads(int n); }
extern "C" void redux_set_threads(int threads) { pk::set_num_threads(threads); }
