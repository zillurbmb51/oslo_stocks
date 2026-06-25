#!/opt/homebrew/bin/bash -l

# Log everything
exec >> /Users/zillurrahman/cron_update.log 2>&1
echo "===== $(date) ====="

# 1. Find your conda base path once in your normal terminal:
#    conda info --base
#    and replace the path below with that.
source /Users/zillurrahman/anaconda3/etc/profile.d/conda.sh

# 2. Activate environment
conda activate osl_forecast

# 3. Go to project directory
cd /Users/zillurrahman/Desktop/Desktop/zillur/work/stock/myfirst_website

# 4. Run your script
python3 app/update_actual_prices.py

# 5. Commit and push
git add data/oslo_actual_prices.csv
git commit -m "Updated actual price $(date +%F)" || echo "Nothing to commit"
git push

