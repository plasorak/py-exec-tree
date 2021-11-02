# ExecutableTree

## TODO:
 - command order
 - transitions configuration:
   - `strict` (won't initiate if node isn't consistent)
   - `complaisant` (will initiate if node isn't consistent and let the applications deal with it)
 - states configuration... This is largely for displaying purpose, I think
   - `optimistic`: node's status is the one of it's children that is the most recent (first command successful)
   - `pessimistic`: node's status is the one of it's children that is the oldest (last command failed)
 - more error handling
