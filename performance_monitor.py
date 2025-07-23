#!/usr/bin/env python3
"""
Performance monitoring and optimization script for VSL Transcription App
"""

import os
import psutil
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

class PerformanceMonitor:
    def __init__(self, app_name="vsl-transcription-app"):
        self.app_name = app_name
        self.log_file = "performance.log"
        self.cache_dir = Path("cache")
        self.temp_dir = Path("temp")
        self.output_dir = Path("outputs")
        
    def get_system_stats(self):
        """Get current system performance statistics"""
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=1)
        disk = psutil.disk_usage('/')
        
        return {
            'timestamp': datetime.now().isoformat(),
            'memory': {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent,
                'used': memory.used
            },
            'cpu': {
                'percent': cpu,
                'count': psutil.cpu_count()
            },
            'disk': {
                'total': disk.total,
                'free': disk.free,
                'percent': disk.free / disk.total * 100
            }
        }
    
    def get_app_processes(self):
        """Find application processes and their resource usage"""
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_percent', 'cpu_percent']):
            try:
                if any(self.app_name in ' '.join(proc.info['cmdline'] or [])):
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'memory_percent': proc.info['memory_percent'],
                        'cpu_percent': proc.info['cpu_percent']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return processes
    
    def analyze_cache_usage(self):
        """Analyze cache directory usage and suggest optimizations"""
        cache_stats = {
            'total_files': 0,
            'total_size': 0,
            'old_files': 0,
            'old_files_size': 0,
            'file_types': {}
        }
        
        if self.cache_dir.exists():
            current_time = time.time()
            for file_path in self.cache_dir.rglob('*'):
                if file_path.is_file():
                    stat = file_path.stat()
                    cache_stats['total_files'] += 1
                    cache_stats['total_size'] += stat.st_size
                    
                    # Files older than 1 day
                    if current_time - stat.st_mtime > 86400:
                        cache_stats['old_files'] += 1
                        cache_stats['old_files_size'] += stat.st_size
                    
                    # Count by extension
                    ext = file_path.suffix
                    cache_stats['file_types'][ext] = cache_stats['file_types'].get(ext, 0) + 1
        
        return cache_stats
    
    def cleanup_old_files(self, max_age_hours=24):
        """Clean up old cache and temporary files"""
        cleaned_files = 0
        cleaned_size = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for directory in [self.cache_dir, self.temp_dir]:
            if directory.exists():
                for file_path in directory.rglob('*'):
                    if file_path.is_file():
                        try:
                            stat = file_path.stat()
                            if current_time - stat.st_mtime > max_age_seconds:
                                cleaned_size += stat.st_size
                                file_path.unlink()
                                cleaned_files += 1
                        except Exception as e:
                            print(f"Error cleaning {file_path}: {e}")
        
        return cleaned_files, cleaned_size
    
    def optimize_memory(self):
        """Suggest memory optimizations"""
        suggestions = []
        memory = psutil.virtual_memory()
        
        if memory.percent > 80:
            suggestions.append("High memory usage detected (>80%). Consider:")
            suggestions.append("- Reducing batch size in transcription")
            suggestions.append("- Clearing cache files")
            suggestions.append("- Restarting the application")
        
        cache_stats = self.analyze_cache_usage()
        if cache_stats['total_size'] > 1024 * 1024 * 1024:  # 1GB
            suggestions.append(f"Cache size is large ({cache_stats['total_size'] / (1024**3):.1f}GB)")
            suggestions.append("- Run cache cleanup")
            suggestions.append("- Consider reducing cache retention time")
        
        return suggestions
    
    def benchmark_model_loading(self):
        """Benchmark model loading times"""
        try:
            import sys
            sys.path.append('.')
            from transcriptor import get_whisper_model, get_alignment_model
            
            results = {}
            
            # Benchmark WhisperX model
            start_time = time.time()
            get_whisper_model()
            results['whisper_model'] = time.time() - start_time
            
            # Benchmark alignment model
            start_time = time.time()
            get_alignment_model()
            results['alignment_model'] = time.time() - start_time
            
            return results
        except Exception as e:
            return {'error': str(e)}
    
    def generate_report(self):
        """Generate comprehensive performance report"""
        report = {
            'system_stats': self.get_system_stats(),
            'app_processes': self.get_app_processes(),
            'cache_analysis': self.analyze_cache_usage(),
            'optimization_suggestions': self.optimize_memory(),
            'model_benchmarks': self.benchmark_model_loading()
        }
        
        return report
    
    def monitor_continuously(self, interval=60, duration=None):
        """Monitor performance continuously"""
        start_time = time.time()
        print(f"Starting continuous monitoring (interval: {interval}s)")
        
        try:
            while True:
                stats = self.get_system_stats()
                processes = self.get_app_processes()
                
                print(f"\n[{stats['timestamp']}]")
                print(f"Memory: {stats['memory']['percent']:.1f}%")
                print(f"CPU: {stats['cpu']['percent']:.1f}%")
                print(f"Disk Free: {stats['disk']['percent']:.1f}%")
                
                if processes:
                    print("App Processes:")
                    for proc in processes:
                        print(f"  PID {proc['pid']}: CPU {proc['cpu_percent']:.1f}%, MEM {proc['memory_percent']:.1f}%")
                else:
                    print("No app processes found")
                
                # Check if duration limit reached
                if duration and (time.time() - start_time) > duration:
                    break
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")

def main():
    parser = argparse.ArgumentParser(description="VSL App Performance Monitor")
    parser.add_argument('--action', choices=['report', 'cleanup', 'monitor', 'benchmark'], 
                       default='report', help='Action to perform')
    parser.add_argument('--interval', type=int, default=60, 
                       help='Monitoring interval in seconds (for monitor action)')
    parser.add_argument('--duration', type=int, 
                       help='Monitoring duration in seconds (for monitor action)')
    parser.add_argument('--max-age', type=int, default=24, 
                       help='Maximum age for files in hours (for cleanup action)')
    
    args = parser.parse_args()
    monitor = PerformanceMonitor()
    
    if args.action == 'report':
        report = monitor.generate_report()
        print(json.dumps(report, indent=2, default=str))
        
    elif args.action == 'cleanup':
        print("Cleaning up old files...")
        cleaned_files, cleaned_size = monitor.cleanup_old_files(args.max_age)
        print(f"Cleaned {cleaned_files} files, freed {cleaned_size / (1024**2):.1f} MB")
        
    elif args.action == 'monitor':
        monitor.monitor_continuously(args.interval, args.duration)
        
    elif args.action == 'benchmark':
        print("Benchmarking model loading...")
        results = monitor.benchmark_model_loading()
        print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()